"""文件模型"""
from sqlalchemy import String, Integer, ForeignKey, Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional
import enum

from .base import Base, TimestampMixin


class FileCategory(str, enum.Enum):
    PUBLIC = "PUBLIC"  # 通用文件
    AVATAR = "AVATAR"  # 头像
    SCORE_PROOF = "SCORE_PROOF"  # 加分证明
    PROOF = "PROOF"  # 普通证明


class FileMetadata(Base, TimestampMixin):
    """文件元数据表"""
    __tablename__ = "file_metadata"

    object_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[Optional[str]] = mapped_column(String(100))
    file_extension: Mapped[Optional[str]] = mapped_column(String(10))
    bucket_name: Mapped[str] = mapped_column(String(100), nullable=False)
    file_category: Mapped[str] = mapped_column(String(50), nullable=False)
    file_purpose: Mapped[Optional[str]] = mapped_column(String(200))
    upload_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    delete_time: Mapped[Optional[str]] = mapped_column(String(50))


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
