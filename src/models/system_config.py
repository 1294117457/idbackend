"""系统配置模型"""

from datetime import datetime, timezone

from sqlalchemy import String, JSON, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional

from .base import Base, TimestampMixin


class ConfigCategory(str):
    """配置分类枚举"""
    RAG = "RAG"
    LLM = "LLM"
    EMBED = "EMBED"
    SMTP = "SMTP"
    AGENT = "AGENT"
    OTHER = "OTHER"


class ConfigValueType(str):
    """配置值类型枚举"""
    STRING = "string"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    JSON = "json"


class SystemConfig(Base):
    """系统配置表

    使用 config_key 作为主键，支持分类和敏感字段标记。
    """

    __tablename__ = "system_config"

    config_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    config_value: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(50), nullable=False, default=ConfigCategory.OTHER)
    value_type: Mapped[str] = mapped_column(String(20), nullable=False, default=ConfigValueType.STRING)
    is_sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class AgentSession(Base, TimestampMixin):
    """Agent 会话表"""

    __tablename__ = "agent_sessions"

    user_id: Mapped[int] = mapped_column()
    session_id: Mapped[str] = mapped_column(String(100), unique=True)
    session_metadata: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
