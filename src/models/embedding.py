"""向量模型"""
import enum
from sqlalchemy import String, Integer, Index
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector as _PgVector
from sqlalchemy.types import TypeDecorator
import numpy as np


class AsyncpgVector(_PgVector):
    """兼容 asyncpg 的 Vector 类型。
    
    asyncpg 会自动将 pgvector 的值解码为 Python list，
    但 pgvector 的 result_processor 期望字符串输入。
    此类覆写 result_processor 以处理两种情况。
    """

    def result_processor(self, dialect, coltype):
        def process(value):
            if value is None:
                return None
            if isinstance(value, list):
                return value
            if isinstance(value, np.ndarray):
                return value.tolist()
            # 字符串格式 (psycopg2 等驱动)
            from pgvector.vector import Vector as VectorUtil
            return VectorUtil._from_db(value)
        return process


from .base import Base, TimestampMixin


class EmbeddingCategory(str, enum.Enum):
    """向量类型"""
    POLICY = "POLICY"              # 政策文件
    SYSTEM_GUIDE = "SYSTEM_GUIDE"  # 系统介绍文档
    TEMPLATE = "TEMPLATE"          # 模板
    FAQ = "FAQ"                     # 常见问题（未来扩展）


class Embedding(Base, TimestampMixin):
    """统一向量表（每行存一个 chunk）"""
    __tablename__ = "embeddings"

    source_id: Mapped[str] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="来源标识（同源所有 chunk 共享，如 doc_xxx / tpl_123）",
    )
    chunk_index: Mapped[int] = mapped_column(
        Integer,
        nullable=True,
        default=0,
        comment="chunk 序号（从 0 开始）",
    )
    title: Mapped[str] = mapped_column(
        String(200),
        nullable=True,
        comment="文档标题",
    )
    content: Mapped[str] = mapped_column(
        String,
        nullable=False,
        comment="chunk 内容",
    )
    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="业务类型：POLICY / SYSTEM_GUIDE / TEMPLATE",
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        AsyncpgVector(1024),
        nullable=True,
        comment="1024 维 embedding 向量（pgvector）",
    )

    __table_args__ = (
        Index("ix_embeddings_category", "category"),
        Index("ix_embeddings_source_id", "source_id"),
    )
