"""向量模型"""
import enum
from sqlalchemy import String, Integer, Index
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from .base import Base, TimestampMixin


class EmbeddingCategory(str, enum.Enum):
    """向量类型"""
    POLICY = "POLICY"              # 政策文件
    SYSTEM_GUIDE = "SYSTEM_GUIDE"  # 系统介绍文档
    TEMPLATE = "TEMPLATE"          # 模板
    FAQ = "FAQ"                     # 常见问题（未来扩展）


class Embedding(Base, TimestampMixin):
    """统一向量表"""
    __tablename__ = "embeddings"

    title: Mapped[str] = mapped_column(
        String(200),
        nullable=True,
        comment="标题（方便人类识别）",
    )
    content: Mapped[str] = mapped_column(
        String,
        nullable=False,
        comment="内容原文（检索后展示用）",
    )
    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="业务类型：POLICY / SYSTEM_GUIDE / TEMPLATE",
    )
    ref_id: Mapped[int] = mapped_column(
        Integer,
        nullable=True,
        index=True,
        comment="关联业务 ID（如 template.id）",
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(1024),
        nullable=True,
        comment="1024 维 embedding 向量（pgvector）",
    )

    __table_args__ = (
        Index("ix_category", "category"),
        Index("ix_ref_id", "ref_id"),
        Index("ix_category_ref_id", "category", "ref_id"),
    )
