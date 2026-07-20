"""文件模型"""
from sqlalchemy import String, Integer, ForeignKey, Boolean, JSON, Enum, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional
import enum

from .base import Base, TimestampMixin


class FileCategory(str, enum.Enum):
    """文件分类（决定访问控制和 S3 路径前缀）"""
    AVATAR = "AVATAR"        # 头像，公开读，返回直链
    PROOF = "PROOF"          # 申请证明材料，严格鉴权，预签名 URL
    POLICY = "POLICY"        # 政策文件，宽松鉴权，预签名 URL
    EDITOR = "EDITOR"        # 富文本图片（template/rule/policy 等编辑器内嵌图），仅校验登录态，预签名 URL


class FileMetadata(Base, TimestampMixin):
    """
    文件元数据表

    本质：S3 对象的数据库索引
    - 存什么：S3 位置、分类、上传人、软删除标志
    - 不存什么：bucket 名（配置项）、文件权限规则（代码逻辑）
    """
    __tablename__ = "file_metadata"

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


class PolicyDocument(Base, TimestampMixin):
    """政策文档表 (用于 RAG)"""
    __tablename__ = "policy_documents"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(50))
    source_url: Mapped[Optional[str]] = mapped_column(String(500))
    embedding: Mapped[Optional[str]] = mapped_column(String)
    doc_metadata: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
