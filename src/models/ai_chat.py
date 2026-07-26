"""AI Chat 数据模型

ORM 实体定义：
- AgentSession: 会话
- AgentMessage: 消息
- AgentSessionSummary: 摘要
- AgentSessionSnapshot: 快照
"""
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any

from sqlalchemy import String, Text, Integer, Boolean, ForeignKey, DateTime, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB

from src.models.base import Base, TimestampMixin


class SessionStatus(str, Enum):
    """会话状态"""
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class MessageRole(str, Enum):
    """消息角色"""
    USER = "USER"
    ASSISTANT = "ASSISTANT"
    SYSTEM = "SYSTEM"


class MessageType(str, Enum):
    """消息类型"""
    TEXT = "TEXT"
    SUGGESTION = "SUGGESTION"
    INTERRUPT = "INTERRUPT"


class AgentSession(Base, TimestampMixin):
    """AI 会话"""
    __tablename__ = "agent_sessions"

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="新会话")
    status: Mapped[SessionStatus] = mapped_column(
        SQLEnum(SessionStatus),
        default=SessionStatus.ACTIVE,
        nullable=False,
    )

    # 关联
    messages: Mapped[List["AgentMessage"]] = relationship(
        "AgentMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="AgentMessage.seq",
    )
    summaries: Mapped[List["AgentSessionSummary"]] = relationship(
        "AgentSessionSummary",
        back_populates="session",
        cascade="all, delete-orphan",
    )
    snapshot: Mapped[Optional["AgentSessionSnapshot"]] = relationship(
        "AgentSessionSnapshot",
        back_populates="session",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<AgentSession(id={self.id}, user_id={self.user_id}, title={self.title})>"


class AgentMessage(Base, TimestampMixin):
    """AI 消息"""
    __tablename__ = "agent_messages"

    session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[MessageRole] = mapped_column(
        SQLEnum(MessageRole),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    msg_type: Mapped[MessageType] = mapped_column(
        SQLEnum(MessageType),
        default=MessageType.TEXT,
        nullable=False,
    )
    sources: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
    )
    tool_calls: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 关联
    session: Mapped["AgentSession"] = relationship(
        "AgentSession",
        back_populates="messages",
    )

    def __repr__(self) -> str:
        return f"<AgentMessage(id={self.id}, session_id={self.session_id}, role={self.role})>"


class AgentSessionSummary(Base, TimestampMixin):
    """AI 会话摘要（用于上下文压缩）

    - is_archived=False: 近期摘要, 最多 N 条, 每条独立
    - is_archived=True:  历史摘要, 最多 1 条, 是合并态
    """
    __tablename__ = "agent_session_summaries"

    session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    start_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # false=近期, true=历史
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # 关联
    session: Mapped["AgentSession"] = relationship(
        "AgentSession",
        back_populates="summaries",
    )

    def __repr__(self) -> str:
        return (
            f"<AgentSessionSummary(id={self.id}, session_id={self.session_id}, "
            f"is_archived={self.is_archived})>"
        )


class AgentSessionSnapshot(Base, TimestampMixin):
    """AI 会话快照（记录压缩状态）

    - 不再每次写消息都更新, 仅在压缩流程时变化
    - 通过 `last_summary_end_seq` + `MAX(seq)` 差值判断是否触发压缩
    """
    __tablename__ = "agent_session_snapshots"

    session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    # 上次摘要覆盖的最后一条消息 seq（判断压缩触发的核心字段）
    last_summary_end_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 当前"近期摘要"数量 (冗余字段, 避免每次 COUNT)
    recent_summary_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 上次压缩时间
    last_summary_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 总摘要数（含历史）, 用于前端展示
    total_summary_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 关联
    session: Mapped["AgentSession"] = relationship(
        "AgentSession",
        back_populates="snapshot",
    )

    def __repr__(self) -> str:
        return (
            f"<AgentSessionSnapshot(id={self.id}, session_id={self.session_id}, "
            f"last_summary_end_seq={self.last_summary_end_seq})>"
        )


__all__ = [
    "AgentSession",
    "AgentMessage",
    "AgentSessionSummary",
    "AgentSessionSnapshot",
    "SessionStatus",
    "MessageRole",
    "MessageType",
]
