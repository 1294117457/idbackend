"""文件模型"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, ForeignKey, Boolean, JSON, Enum, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, TYPE_CHECKING
import enum

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    pass


class FileCategory(str, enum.Enum):
    """文件分类（决定访问控制和 S3 路径前缀）"""
    AVATAR = "AVATAR"        # 头像，公开读，返回直链
    PROOF = "PROOF"          # 申请证明材料，严格鉴权，预签名 URL
    POLICY = "POLICY"        # 政策文件，宽松鉴权，预签名 URL
    EDITOR = "EDITOR"        # 富文本图片（template/rule/policy 等编辑器内嵌图），仅校验登录态，预签名 URL


class FileMetadata(Base, TimestampMixin):
    __tablename__ = "file_metadata"

    # 支持直接预览的类型（浏览器原生支持，无需任何服务端转换）
    PREVIEWABLE_TYPES: frozenset[str] = frozenset({
        # 图片
        "image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml",
        # PDF
        "application/pdf",
    })

    @property
    def can_preview(self) -> bool:
        """是否能直接预览（无需转换）"""
        return self.content_type in self.PREVIEWABLE_TYPES if self.content_type else False

    # S3 定位（核心字段）
    object_name: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True,
        comment="S3 对象 key，如 files/proofs/2025/123/abc.pdf",
    )

    # 文件原始信息
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[Optional[str]] = mapped_column(String(100))
    file_extension: Mapped[Optional[str]] = mapped_column(String(10))

    # 分类与归属（鉴权核心字段）
    file_category: Mapped[FileCategory] = mapped_column(
        Enum(FileCategory, native_enum=False, length=20),
        nullable=False, index=True,
        comment="决定鉴权分支和 S3 路径前缀",
    )
    upload_user_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True,
        comment="上传用户，部分鉴权场景使用",
    )

    # 软删除
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    delete_time: Mapped[Optional[str]] = mapped_column(String(50))

    __table_args__ = (
        Index("ix_file_category_deleted", "file_category", "is_deleted"),
    )

    # 路径前缀映射（类常量）
    PREFIX_MAP = {
        FileCategory.AVATAR: "avatar",
        FileCategory.PROOF: "proof",
        FileCategory.POLICY: "policy",
        FileCategory.EDITOR: "editor",
    }

    @staticmethod
    def build_object_name(category: FileCategory, original_name: str) -> str:
        """生成带前缀的 object_name（领域逻辑）"""
        prefix = FileMetadata.PREFIX_MAP.get(category, "misc")
        ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
        unique_id = uuid.uuid4().hex[:12]
        if ext:
            return f"{prefix}/{unique_id}.{ext}"
        return f"{prefix}/{unique_id}"

    @classmethod
    def create(
        cls,
        category: FileCategory,
        original_name: str,
        content: bytes,
        content_type: str,
        user_id: int,
    ) -> "FileMetadata":
        """工厂方法：创建元数据对象（包含领域逻辑）"""
        object_name = cls.build_object_name(category, original_name)
        ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
        return cls(
            object_name=object_name,
            original_name=original_name,
            file_size=len(content),
            content_type=content_type,
            file_extension=ext,
            file_category=category,
            upload_user_id=user_id,
        )

    def mark_deleted(self) -> None:
        """软删除——领域行为"""
        self.is_deleted = True
        self.delete_time = datetime.now(timezone.utc).isoformat()

    def is_owned_by(self, user_id: int) -> bool:
        """归属校验——领域行为"""
        return self.upload_user_id == user_id
