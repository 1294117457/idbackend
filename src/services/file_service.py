"""文件 Service

设计原则（docs/file/分层设计.md §1）：
- 只做"接请求 → 调存储 → 调 DB → 构造返回对象"四件事
- 数据转换 / 校验 / ORM 构造由 Request DTO（to_metadata / apply_to / to_conditions）承担
- VO 投影由 VO.from_orm_to_vo 在 service 内部完成
- 事务边界由 Service 管理（§13.5 架构决策：依赖注入层只管 session 生命周期）
"""
import io
import logging
import uuid
from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infra.storage import Storage
from src.models import FileCategory, FileMetadata
from src.app.context import get_user_id
from src.app.schemas import (
    FileUploadRequest,
    FileAvatarUploadRequest,
    FileUpdateRequest,
    FileQueryRequest,
    FileVO,
    FileListVO,
    FileDataVO,
    NotFoundError,
    BadRequestError,
)
from src.exceptions import UnsupportedMediaTypeError

logger = logging.getLogger(__name__)


# ========== Service ==========

class FileService:

    def __init__(self, db: AsyncSession, storage: Storage):
        self._db = db
        self._storage = storage

    # ---- 内部辅助 ----

    async def _safe_delete(self, key: str, ignore_error: bool = True) -> None:

        try:
            await self._storage.delete(key)
        except Exception as e:
            if ignore_error:
                print(f"[FileService] MinIO 删除失败（忽略）: {key} - {e}")
            else:
                print(f"[FileService] MinIO 补偿删除失败: {key} - {e}")
                raise

    async def _get_metadata_or_404(self, file_id: int) -> FileMetadata:
        """通用：按 ID 查文件元数据，不存在抛 404"""
        meta = await self._db.get(FileMetadata, file_id)
        if not meta or meta.is_deleted:
            raise NotFoundError(f"文件不存在：file_id={file_id}")
        return meta

    # ---- 上传 ----

    async def upload_file(self, req: FileUploadRequest) -> Tuple[FileMetadata, str]:
        """上传文件到 MinIO + 写入 DB 元数据。

        事务边界（Step 5 后）：
        - DB 提交：由 get_db 框架统一管理
        - MinIO 上传：在 DB 提交前完成（顺序不可换）
        - 失败补偿：
            * MinIO 上传失败：直接抛异常，不污染 DB（理想路径）
            * DB 写入失败（框架 commit 时）：产生 MinIO 孤儿对象
              → 由定期清理任务处理（见 docs/docs-backend/dbremake/minio-orphans.md）

        为什么不再 service 内做 MinIO 补偿？
        - 框架 commit 在路由 return 后才发生，service 无法精确捕获失败点
        - 分布式两阶段提交无法完美解决，业界方案是"接受孤儿 + 定期清理"
        """
        user_id = get_user_id()
        metadata = req.to_metadata(user_id)
        key = metadata.object_name

        # 第 1 步：上传 MinIO（失败直接抛异常，不影响 DB）
        await self._storage.upload(
            file_obj=io.BytesIO(req.content),
            key=key,
            content_type=metadata.content_type,
        )

        # 第 2 步：标记 DB 对象（框架 commit 在路由 return 时发生）
        self._db.add(metadata)

        # ↑ 如果框架 commit 失败：
        #    - DB rollback（数据不写入）
        #    - MinIO 对象留下孤儿
        #    - 定期清理任务处理（最终一致性）

        # 返回下载签名 URL（带 attachment），1 小时有效
        return metadata, self._storage.get_presigned_download_url(
            key=metadata.object_name,
            original_name=metadata.original_name,
            expiry=3600,
            as_attachment=True,
        )

    async def upload_avatar(
        self,
        req: FileAvatarUploadRequest,
    ) -> Tuple[FileMetadata, str]:
        """上传头像 + 清理旧头像。

        事务边界（Step 5 后）：
        - 新旧头像处理在同一个事务（框架 commit）
        - MinIO 上传新头像：在 DB 提交前
        - MinIO 删除旧头像：不在 service 内做（接受孤儿 + 定期清理）
        """
        user_id = get_user_id()

        # 用 Model 的工厂方法创建元数据（包含路径生成逻辑）
        new_meta = FileMetadata.create(
            category=FileCategory.AVATAR,
            original_name=req.originalName,
            content=req.content,
            content_type=req.contentType,
            user_id=user_id,
        )

        # 找旧头像（允许不存在）
        old: Optional[FileMetadata] = (await self._db.execute(
            select(FileMetadata).where(
                FileMetadata.file_category == FileCategory.AVATAR,
                FileMetadata.upload_user_id == user_id,
                FileMetadata.is_deleted == False,
            )
        )).scalar_one_or_none()

        # 第 1 步：上传新头像到 MinIO
        await self._storage.upload(
            file_obj=io.BytesIO(req.content),
            key=new_meta.object_name,
            content_type=new_meta.content_type,
        )

        # 第 2 步：DB 标记新头像
        self._db.add(new_meta)

        # 第 3 步：DB 标记旧头像为删除
        # ↑ 同一个事务里，框架 commit 一次性 commit
        if old and old.object_name != new_meta.object_name:
            old.mark_deleted()
            # ↑ 旧头像 MinIO 对象不在本次删除（接受孤儿 + 定期清理）

        # 第 4 步：返回公开直链（Policy 已设置 avatar/ 公开）
        return new_meta, self._storage.get_public_url(new_meta.object_name)

    # ---- 查询 ----

    async def search_files(self, req: FileQueryRequest) -> FileListVO:

        conditions = [FileMetadata.is_deleted == False, *req.to_conditions()]

        # 计数
        count_result = await self._db.execute(
            select(func.count()).select_from(FileMetadata).where(*conditions)
        )
        total = count_result.scalar() or 0

        # 分页查询
        query = (
            select(FileMetadata)
            .where(*conditions)
            .order_by(FileMetadata.created_at.desc())
            .offset((req.pageNum - 1) * req.pageSize)
            .limit(req.pageSize)
        )
        result = await self._db.execute(query)
        files = list(result.scalars().all())

        return FileListVO.from_list_to_page(
            items=[FileVO.from_orm_to_vo(f) for f in files],
            total=total,
            page_num=req.pageNum,
            page_size=req.pageSize,
        )

    # ---- 预览 / 下载（v8.0 统一接口）----

    async def get_preview_for_inline(self, file_id: int) -> Tuple[FileVO, bytes]:
        from src.infra.config import get_settings

        meta = await self._get_metadata_or_404(file_id)

        if not meta.can_preview:
            raise UnsupportedMediaTypeError(f"文件「{meta.original_name}」不支持预览")

        settings = get_settings()
        if meta.file_size > settings.MAX_PREVIEW_FILE_SIZE:
            from fastapi import HTTPException, status
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"预览文件大小不能超过 {settings.MAX_PREVIEW_FILE_SIZE // (1024 * 1024)}MB",
            )

        data = await self._storage.download(meta.object_name)
        return FileVO.from_orm_to_vo(meta), data

    # ---- 更新 / 删除 ----

    async def update_file(self, req: FileUpdateRequest, file_id: int) -> FileVO:
        meta = await self._get_metadata_or_404(file_id)

        if not req.apply_to(meta):
            return FileVO.from_orm_to_vo(meta)
        # ↑ dirty 状态保留 → 框架 commit 时一起更新
        return FileVO.from_orm_to_vo(meta)

    async def get_download_data(self, file_id: int, expiry_minutes: int = 60) -> FileDataVO:
        """获取文件的下载数据（签名 URL）

        - 查询文件元数据，不存在抛 404
        - 返回签名 URL，有效期由 expiry_minutes 控制
        """
        meta = await self._get_metadata_or_404(file_id)
        url = self._storage.get_presigned_download_url(
            key=meta.object_name,
            original_name=meta.original_name,
            expiry=expiry_minutes * 60,
            as_attachment=True,
        )
        return FileDataVO.from_orm_to_vo(meta, url)

    async def delete_file(self, file_id: int) -> None:
        meta = await self._get_metadata_or_404(file_id)

        # EDITOR 类型不应走此路径
        if meta.file_category == FileCategory.EDITOR:
            raise BadRequestError("富文本图片不应通过此接口删除")

        meta.mark_deleted()
        # ↑ dirty 状态保留 → 框架 commit 时更新
        # MinIO 物理删除不在 service 内做（接受孤儿 + 定期清理）