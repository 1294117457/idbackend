"""文件 Service

设计原则（docs/file/分层设计.md §1）：
- 只做"接请求 → 调存储 → 调 DB → 构造返回对象"四件事
- 数据转换 / 校验 / ORM 构造由 Request DTO（to_metadata / apply_to / to_conditions）承担
- VO 投影由 VO.from_orm_to_vo 在 service 内部完成
- 事务边界由 Service 管理（§13.5 架构决策：依赖注入层只管 session 生命周期）
"""
import io
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
)


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

        # v6.0：返回下载签名 URL（带 attachment），1 小时有效
        return metadata, self._storage.get_download_url(
            metadata.object_name,
            original_name=metadata.original_name,
            expiry=3600,
            force_attachment=True,
        )

    async def upload_avatar(
        self,
        req: FileAvatarUploadRequest,
    ) -> Tuple[FileMetadata, str]:

        user_id = get_user_id()
        new_meta = req.to_metadata(user_id)

        # 找旧头像（允许不存在）
        old: Optional[FileMetadata] = (await self._db.execute(
            select(FileMetadata).where(
                FileMetadata.file_category == FileCategory.AVATAR,
                FileMetadata.upload_user_id == user_id,
                FileMetadata.is_deleted == False,
            )
        )).scalar_one_or_none()

        # 上传新头像
        await self._storage.upload(
            file_obj=io.BytesIO(req.content),
            key=new_meta.object_name,
            content_type=new_meta.content_type,
        )

        # 事务 1：写新记录
        self._db.add(new_meta)
        try:
            await self._db.commit()
        except Exception:
            await self._safe_delete(new_meta.object_name, ignore_error=False)
            await self._db.rollback()
            raise
        await self._db.refresh(new_meta)

        # 事务 2：清理旧头像（独立事务，不阻塞主流程）
        if old and old.object_name != new_meta.object_name:
            old.is_deleted = True
            old.delete_time = datetime.utcnow().isoformat()
            try:
                await self._db.commit()
                await self._safe_delete(old.object_name, ignore_error=True)
            except Exception:
                await self._db.rollback()

        return new_meta, self._storage.get_download_url(
            new_meta.object_name,
            original_name=new_meta.original_name,
            expiry=86400 * 7,           # 头像默认 7 天（业务长期展示）
            force_attachment=False,     # 头像预览用，不强制下载
        )

    # ---- 查询 ----

    async def get_file(self, file_id: int) -> FileMetadata:

        result = await self._db.execute(
            select(FileMetadata).where(
                FileMetadata.id == file_id,
                FileMetadata.is_deleted == False,
            )
        )
        meta = result.scalar_one_or_none()
        if not meta:
            raise NotFoundError(f"文件不存在：file_id={file_id}")
        return meta

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

        # ORM → VO + 分页封装，全在 service 层完成
        return FileListVO.from_list_to_page(
            items=[FileVO.from_orm_to_vo(f) for f in files],
            total=total,
            page_num=req.pageNum,
            page_size=req.pageSize,
        )

    # ---- 预览 / 下载（v6.0 全签名模式）----

    async def get_preview_data(
        self,
        file_id: int,
        expiry_minutes: int = 60,
    ) -> Tuple[FileMetadata, str]:
        """返回 (meta, url)——v6.0 统一签名 URL，移除 AVATAR 公开直链特例

        所有 fileCategory 一律走 presigned URL，过期时间由 expiry_minutes 控制。
        preview 场景 force_attachment=False：浏览器按 Content-Type 内联展示。
        """
        meta = await self.get_file(file_id)
        url = self._storage.get_download_url(
            meta.object_name,
            original_name=meta.original_name,
            expiry=expiry_minutes * 60,
            force_attachment=False,
        )
        return meta, url

    async def get_download_data(
        self,
        file_id: int,
        expiry_minutes: int = 60,
    ) -> Tuple[FileMetadata, str]:
        """v6.0：返回 (meta, url)——预签名下载 URL，后端不再中转字节

        - 后端零带宽（MinIO 直发前端）
        - URL 带 Content-Disposition: attachment（浏览器强制下载）
        - 默认 60min 过期，前端可在 query 调整 expiryMinutes（1~1440）
        """
        meta = await self.get_file(file_id)
        url = self._storage.get_download_url(
            meta.object_name,
            original_name=meta.original_name,
            expiry=expiry_minutes * 60,
            force_attachment=True,
        )
        return meta, url

    async def get_preview_bytes(self, file_id: int) -> Tuple[FileMetadata, bytes]:
        """返回 (meta, bytes)——用于后端代理预览接口

        校验文件大小不超过 MAX_PREVIEW_FILE_SIZE（默认 5MB），
        超过则抛异常，由路由层返回 413。
        """
        from src.infra.config import get_settings

        meta = await self.get_file(file_id)
        data = await self._storage.download(meta.object_name)

        settings = get_settings()
        if len(data) > settings.MAX_PREVIEW_FILE_SIZE:
            from fastapi import HTTPException, status
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"预览文件大小不能超过 {settings.MAX_PREVIEW_FILE_SIZE // (1024 * 1024)}MB",
            )
        return meta, data

    # ---- 更新 / 删除 ----

    async def update_file(self, req: FileUpdateRequest, file_id: int) -> FileMetadata:

        meta = await self.get_file(file_id)
        if not req.apply_to(meta):
            return meta  # 无字段被修改，不触发 commit
        await self._db.commit()
        await self._db.refresh(meta)
        return meta

    async def delete_file(self, file_id: int) -> None:
        meta = await self.get_file(file_id)
        meta.is_deleted = True
        meta.delete_time = datetime.utcnow().isoformat()
        await self._db.commit()