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

        user_id = get_user_id()
        metadata = req.to_metadata(user_id)
        key = metadata.object_name

        await self._storage.upload(
            file_obj=io.BytesIO(req.content),
            key=key,
            content_type=metadata.content_type,
        )

        self._db.add(metadata)
        try:
            await self._db.commit()
        except Exception:
            # 补偿删除：失败要 raise，外层需要感知（避免孤儿 MinIO 对象）
            await self._safe_delete(key, ignore_error=False)
            await self._db.rollback()
            raise
        await self._db.refresh(metadata)

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

        # 2. 上传到 MinIO
        await self._storage.upload(
            file_obj=io.BytesIO(req.content),
            key=new_meta.object_name,
            content_type=new_meta.content_type,
        )

        # 3. 事务 1：写新记录
        self._db.add(new_meta)
        try:
            await self._db.commit()
        except Exception:
            await self._safe_delete(new_meta.object_name, ignore_error=False)
            await self._db.rollback()
            raise
        await self._db.refresh(new_meta)

        # 4. 事务 2：清理旧头像（独立事务，不阻塞主流程）
        if old and old.object_name != new_meta.object_name:
            old.mark_deleted()
            try:
                await self._db.commit()
                await self._safe_delete(old.object_name, ignore_error=True)
            except Exception:
                await self._db.rollback()

        # 5. 返回公开直链（Policy 已设置 avatar/ 公开）
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
        await self._db.commit()
        await self._db.refresh(meta)
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
        await self._db.commit()