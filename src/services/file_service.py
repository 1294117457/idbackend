"""文件服务"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from datetime import datetime
import uuid

from src.infra.s3 import S3Client, get_s3_client
from src.models import FileMetadata, FileCategory


class FileService:
    """文件服务"""

    @staticmethod
    async def upload_file(
        db: AsyncSession,
        file_data: bytes,
        original_name: str,
        content_type: str,
        user_id: int,
        category: str = FileCategory.PUBLIC.value,
        purpose: str = "",
    ) -> tuple[FileMetadata, str]:
        """上传文件"""
        s3_client = get_s3_client()

        # 生成唯一文件名
        ext = original_name.rsplit(".", 1)[-1] if "." in original_name else ""
        object_name = f"{uuid.uuid4()}.{ext}" if ext else str(uuid.uuid4())

        # 上传到 S3
        s3_client.upload_file(file_data, object_name, content_type)

        # 获取预览 URL
        preview_url = s3_client.get_presigned_url(object_name)

        # 保存元数据
        file_meta = FileMetadata(
            object_name=object_name,
            original_name=original_name,
            file_size=len(file_data),
            content_type=content_type,
            file_extension=ext,
            bucket_name=s3_client.bucket,
            file_category=category,
            file_purpose=purpose,
            upload_user_id=user_id,
        )
        db.add(file_meta)
        await db.commit()
        await db.refresh(file_meta)

        return file_meta, preview_url

    @staticmethod
    async def get_file_by_id(
        db: AsyncSession,
        file_id: int,
    ) -> Optional[FileMetadata]:
        """根据ID获取文件元数据"""
        result = await db.execute(
            select(FileMetadata).where(
                FileMetadata.id == file_id,
                FileMetadata.is_deleted == False,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_preview_url(
        db: AsyncSession,
        file_id: int,
    ) -> Optional[str]:
        """获取文件预览URL"""
        file_meta = await FileService.get_file_by_id(db, file_id)
        if not file_meta:
            return None

        s3_client = get_s3_client()
        return s3_client.get_presigned_url(file_meta.object_name)

    @staticmethod
    async def download_file(
        db: AsyncSession,
        file_id: int,
    ) -> Optional[tuple[bytes, str]]:
        """下载文件"""
        file_meta = await FileService.get_file_by_id(db, file_id)
        if not file_meta:
            return None

        s3_client = get_s3_client()
        file_data = s3_client.download_file(file_meta.object_name)

        return file_data, file_meta.content_type

    @staticmethod
    async def delete_file(
        db: AsyncSession,
        file_id: int,
        user_id: int,
    ) -> bool:
        """删除文件 (软删除)"""
        file_meta = await FileService.get_file_by_id(db, file_id)
        if not file_meta:
            return False

        # 检查权限
        if file_meta.upload_user_id != user_id:
            return False

        # 软删除
        file_meta.is_deleted = True
        file_meta.delete_time = datetime.utcnow().isoformat()

        await db.commit()
        return True

    @staticmethod
    async def search_files(
        db: AsyncSession,
        user_id: Optional[int] = None,
        category: Optional[str] = None,
        filename_keyword: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[List[FileMetadata], int]:
        """搜索文件"""
        query = select(FileMetadata).where(FileMetadata.is_deleted == False)

        if user_id:
            query = query.where(FileMetadata.upload_user_id == user_id)
        if category:
            query = query.where(FileMetadata.file_category == category)
        if filename_keyword:
            query = query.where(FileMetadata.original_name.ilike(f"%{filename_keyword}%"))

        # 获取总数
        from sqlalchemy import func

        count_result = await db.execute(
            select(func.count()).select_from(FileMetadata).where(
                FileMetadata.is_deleted == False
            )
        )
        total = count_result.scalar()

        # 分页
        query = query.order_by(FileMetadata.created_at.desc())
        query = query.offset((page - 1) * size).limit(size)

        result = await db.execute(query)
        files = result.scalars().all()

        return list(files), total

    @staticmethod
    async def upload_avatar(
        db: AsyncSession,
        file_data: bytes,
        user_id: int,
        content_type: str,
    ) -> tuple[FileMetadata, str]:
        """上传头像"""
        return await FileService.upload_file(
            db=db,
            file_data=file_data,
            original_name=f"avatar_{user_id}.jpg",
            content_type=content_type,
            user_id=user_id,
            category=FileCategory.AVATAR.value,
            purpose="avatar",
        )
