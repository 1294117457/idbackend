"""系统配置模型"""
from sqlalchemy import String, JSON
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional

from .base import Base, TimestampMixin


class SystemConfig(Base, TimestampMixin):
    """系统配置表"""
    __tablename__ = "system_config"

    config_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    config_value: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(200))


class AgentSession(Base, TimestampMixin):
    """Agent 会话表"""
    __tablename__ = "agent_sessions"

    user_id: Mapped[int] = mapped_column()
    session_id: Mapped[str] = mapped_column(String(100), unique=True)
    session_metadata: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
