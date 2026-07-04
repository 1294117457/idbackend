import io
import uuid
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infra.storage import Storage
from src.models import (
    Application,
    ApplicationProof,
    FileCategory,
    FileMetadata,
)


# ========== 异常类型 ==========

class _BusinessError(Exception):
    """业务异常基类：自带 HTTP 语义（http_code）

    子类只需设置 http_code / default_message 即可；
    全局 exception_handler（main.py）会自动把它映射成统一 JSONResponse。

    支持两种构造形式：
    - MyError()                                       → 用 default_message
    - MyError("自定义消息")                            → 用自定义消息
    - MyError("code", "message")                      → 兼容旧调用（旧 FileAuthError）
    """
    http_code: int = 500
    default_message: str = "服务器内部错误"

    def __init__(self, *args):
        if len(args) == 0:
            self.message = self.default_message
        elif len(args) == 1:
            self.message = str(args[0])
        elif len(args) == 2:
            # 兼容旧 (code, message) 形式 → 只取 message
            self.message = str(args[1])
        else:
            self.message = self.default_message
        super().__init__(self.message)


class FileAuthError(_BusinessError):
    """文件鉴权失败（鉴权过程中抛出，如 PROOF 三表 JOIN 后无权限）"""
    http_code = 403
    default_message = "鉴权失败"


class FileNotFoundError(_BusinessError):
    """文件不存在（包括已软删除）"""
    http_code = 404
    default_message = "文件不存在"


class FileForbiddenError(_BusinessError):
    """操作不被允许（不是本人 / 没有权限）"""
    http_code = 403
    default_message = "无权访问该文件"


def _build_object_name(category: FileCategory, original_name: str, user_id: int) -> str:
    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if ext and len(ext) > 10:
        ext = ext[:10]

    unique_id = uuid.uuid4().hex
    year = datetime.utcnow().year
    category_prefix = category.value.lower()

    if ext:
        return f"{category_prefix}/{year}/{user_id}/{unique_id}.{ext}"
    return f"{category_prefix}/{year}/{user_id}/{unique_id}"


class FileService:

    def __init__(self, db: AsyncSession, storage: Storage):
        self._db = db
        self._storage = storage

    # ========== 内部辅助 ==========

    @staticmethod
    def _normalize_category(category: str) -> FileCategory:

        if not category:
            return FileCategory.PROOF
        upper = category.upper()

        # 前端语义别名 → 后端 enum
        ALIAS_MAP = {
            "PUBLIC": FileCategory.POLICY,       # 管理员"公共文件"= 政策文件
            "SCORE_PROOF": FileCategory.PROOF,   # 学生"加分证明"
        }
        if upper in ALIAS_MAP:
            return ALIAS_MAP[upper]

        try:
            return FileCategory(upper)
        except ValueError:
            raise ValueError(
                f"不支持的 file_category: {category!r}（仅支持 {[c.value for c in FileCategory]} 或别名 {list(ALIAS_MAP)}）"
            )

    async def _safe_delete(self, key: str, log_only: bool = False) -> None:
        """S3 删除失败不影响主流程（一般 S3 删除失败也不影响业务正确性）"""
        try:
            await self._storage.delete(key)
        except Exception as e:
            if log_only:
                print(f"[FileService] S3 清理失败（忽略）: {key} - {e}")
            else:
                print(f"[FileService] S3 补偿删除失败: {key} - {e}")

    # ========== 上传 ==========

    async def upload_file(
        self,
        file_data: bytes,
        original_name: str,
        content_type: str,
        user_id: int,
        category: str = FileCategory.PROOF.value,
        purpose: str = "",
    ) -> Tuple[FileMetadata, str]:
        """通用文件上传

        顺序：S3 上传 → DB 写入；若 DB 失败则回滚 S3（删孤儿对象）。
        """
        file_category = self._normalize_category(category)
        object_name = _build_object_name(file_category, original_name, user_id)
        ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""

        await self._storage.upload(
            file_obj=io.BytesIO(file_data),
            key=object_name,
            content_type=content_type,
        )

        file_meta = FileMetadata(
            object_name=object_name,
            original_name=original_name,
            file_size=len(file_data),
            content_type=content_type,
            file_extension=ext,
            file_category=file_category,
            file_purpose=purpose,
            upload_user_id=user_id,
        )
        self._db.add(file_meta)
        try:
            await self._db.commit()
        except Exception:
            # DB 写入失败 → 删 S3 孤儿对象
            await self._safe_delete(object_name)
            await self._db.rollback()
            raise
        await self._db.refresh(file_meta)

        return file_meta, self._storage.get_access_url(object_name)

    async def upload_avatar(
        self,
        file_data: bytes,
        user_id: int,
        content_type: str,
    ) -> Tuple[FileMetadata, str]:
        """上传头像

        - 用户只有一个头像：旧头像软删 + 删 S3 旧文件 + 上传新头像
        - 任何一步失败都尽量回滚（前一步的副作用反着来）
        """
        file_category = FileCategory.AVATAR
        object_name = _build_object_name(
            file_category, f"avatar_{user_id}.jpg", user_id
        )

        # 1) 找用户当前未删除的头像记录
        old: Optional[FileMetadata] = (await self._db.execute(
            select(FileMetadata).where(
                FileMetadata.file_category == FileCategory.AVATAR,
                FileMetadata.upload_user_id == user_id,
                FileMetadata.is_deleted == False,
            )
        )).scalar_one_or_none()

        # 2) 上传新头像到 S3
        await self._storage.upload(
            file_obj=io.BytesIO(file_data),
            key=object_name,
            content_type=content_type,
        )

        # 3) 写新头像元数据
        new_meta = FileMetadata(
            object_name=object_name,
            original_name=f"avatar_{user_id}.jpg",
            file_size=len(file_data),
            content_type=content_type,
            file_extension="jpg",
            file_category=file_category,
            file_purpose="avatar",
            upload_user_id=user_id,
        )
        self._db.add(new_meta)
        try:
            await self._db.commit()
        except Exception:
            # 新头像入库失败 → 删 S3 新文件
            await self._safe_delete(object_name)
            await self._db.rollback()
            raise
        await self._db.refresh(new_meta)

        # 4) 旧头像软删 + 清 S3（不阻塞主流程，失败也不影响新头像）
        if old and old.object_name != object_name:
            old.is_deleted = True
            old.delete_time = datetime.utcnow().isoformat()
            try:
                await self._db.commit()
                await self._safe_delete(old.object_name, log_only=True)
            except Exception:
                await self._db.rollback()

        # AVATAR 走直链（Storage ABC 强制每个 Adapter 实现 get_public_url）
        return new_meta, self._storage.get_public_url(object_name)

    # ========== 查询 ==========

    async def get_file_by_id(self, file_id: int) -> Optional[FileMetadata]:
        """根据 ID 获取文件元数据（自动过滤软删除）"""
        result = await self._db.execute(
            select(FileMetadata).where(
                FileMetadata.id == file_id,
                FileMetadata.is_deleted == False,
            )
        )
        return result.scalar_one_or_none()

    # ========== 预览 URL ==========

    async def get_preview_url(
        self,
        file_id: int,
        user_id: int,
        user_permissions: Optional[List[str]] = None,
    ) -> str:
        """获取文件预览 URL

        当前不做业务鉴权（CRUD 阶段）；按分类返回：
        - AVATAR：直链（公开桶）
        - POLICY / PROOF：预签名 URL（带过期时间）

        抛出：
        - FileNotFoundError：文件不存在或已删除
        """
        file_meta = await self.get_file_by_id(file_id)
        if not file_meta:
            raise FileNotFoundError(f"file_id={file_id}")

        if file_meta.file_category == FileCategory.AVATAR:
            return self._storage.get_public_url(file_meta.object_name)

        # POLICY / PROOF 都走预签名
        if file_meta.file_category in (FileCategory.POLICY, FileCategory.PROOF):
            return self._storage.get_access_url(file_meta.object_name)

        raise FileNotFoundError(f"file_id={file_id}：未知分类 {file_meta.file_category}")

    # ========== 下载 ==========
    # 移到下面 get_download_stream（带异常表达语义）

    # ========== 直接按 key 拿 URL（不查 db） ==========

    def get_access_url_by_key(self, object_name: str, expiry: int = 3600) -> str:
        """通过 S3 object_name 直接生成访问 URL（不查 db）

        用于前端已知 object_name 的场景（如 POLICY 类政策文件）。
        需要确保调用方已鉴权（route 层做）。
        """
        return self._storage.get_access_url(object_name, expiry=expiry)

    # ========== 下载流（用于 StreamingResponse） ==========

    async def get_download_stream(
        self,
        file_id: int,
        user_id: int,
        user_permissions: Optional[List[str]] = None,
    ) -> Tuple[bytes, str, str]:
        """获取文件下载的 (bytes, content_type, original_name) 三元组

        当前不做业务鉴权（CRUD 阶段）。

        抛出：
        - FileNotFoundError：文件不存在或已删除
        """
        file_meta = await self.get_file_by_id(file_id)
        if not file_meta:
            raise FileNotFoundError(f"file_id={file_id}")

        file_data = await self._storage.download(file_meta.object_name)
        return (
            file_data,
            file_meta.content_type or "application/octet-stream",
            file_meta.original_name,
        )

    # ========== 更新文件元信息 ==========

    async def update_file_meta(
        self,
        file_id: int,
        user_id: int,
        user_permissions: Optional[List[str]] = None,
        original_name: Optional[str] = None,
        file_purpose: Optional[str] = None,
    ) -> FileMetadata:
        """更新文件元信息（重命名 / 改用途）

        当前不做业务鉴权（CRUD 阶段）。

        抛出：
        - FileNotFoundError：文件不存在或已删除
        """
        file_meta = await self.get_file_by_id(file_id)
        if not file_meta:
            raise FileNotFoundError(f"file_id={file_id}")

        if original_name is not None:
            file_meta.original_name = original_name
        if file_purpose is not None:
            file_meta.file_purpose = file_purpose

        await self._db.commit()
        await self._db.refresh(file_meta)
        return file_meta

    # ========== 删除（软删） ==========

    async def delete_file(
        self,
        file_id: int,
        user_id: int,
        user_permissions: Optional[List[str]] = None,
    ) -> None:
        """软删除文件（仅置 is_deleted=true，不删 S3）

        当前不做业务鉴权（CRUD 阶段）。

        抛出：
        - FileNotFoundError：文件不存在或已删除
        """
        file_meta = await self.get_file_by_id(file_id)
        if not file_meta:
            raise FileNotFoundError(f"file_id={file_id}")

        file_meta.is_deleted = True
        file_meta.delete_time = datetime.utcnow().isoformat()
        await self._db.commit()

    # ========== 搜索 ==========

    async def search_files(
        self,
        user_id: Optional[int] = None,
        category: Optional[str] = None,
        filename_keyword: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        page: int = 1,
        size: int = 20,
    ) -> Tuple[List[FileMetadata], int]:
        """搜索文件（分页）"""
        conditions = [FileMetadata.is_deleted == False]
        if user_id:
            conditions.append(FileMetadata.upload_user_id == user_id)
        if category:
            try:
                conditions.append(FileMetadata.file_category == FileCategory(category.upper()))
            except ValueError:
                conditions.append(FileMetadata.file_category == category)
        if filename_keyword:
            conditions.append(FileMetadata.original_name.ilike(f"%{filename_keyword}%"))
        if start_time:
            conditions.append(FileMetadata.created_at >= start_time)
        if end_time:
            conditions.append(FileMetadata.created_at <= end_time)

        # 计数
        count_result = await self._db.execute(
            select(func.count()).select_from(FileMetadata).where(*conditions)
        )
        total = count_result.scalar() or 0

        # 分页
        query = (
            select(FileMetadata)
            .where(*conditions)
            .order_by(FileMetadata.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        result = await self._db.execute(query)
        files = result.scalars().all()
        return list(files), total