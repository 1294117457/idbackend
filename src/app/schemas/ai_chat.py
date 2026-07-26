"""AI Chat DTO / VO 定义

职责：
- Request DTO：接收前端请求参数
- Response VO：返回给前端的结构化数据
- 转换方法：ORM → VO（from_orm 类方法）
"""
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field, ConfigDict

from src.models.ai_chat import (
    AgentSession,
    AgentMessage,
    SessionStatus,
    MessageRole,
    MessageType,
)
from src.app.schemas.page import Page


# ═══════════════════════════════════════════════════════════════════════════════
# Request DTO
# ═══════════════════════════════════════════════════════════════════════════════


class ChatRequest(BaseModel):
    """对话请求 DTO

    - session_id: 目标会话，null/0 表示新建会话
    - message: 用户输入内容
    """
    model_config = ConfigDict(populate_by_name=True)

    session_id: Optional[int] = Field(default=None, description="会话ID，null/0 表示新建")
    message: str = Field(..., min_length=1, description="用户输入内容")


class SessionListRequest(BaseModel):
    """会话列表请求 DTO"""
    model_config = ConfigDict(populate_by_name=True)

    page_num: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=20, ge=1, le=100, description="每页大小")


# ═══════════════════════════════════════════════════════════════════════════════
# Response VO
# ═══════════════════════════════════════════════════════════════════════════════


class SessionVO(BaseModel):
    """会话 VO"""
    id: int
    title: str
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None

    @classmethod
    def from_orm(cls, session: AgentSession) -> "SessionVO":
        return cls(
            id=session.id,
            title=session.title,
            createdAt=session.created_at.isoformat() if session.created_at else None,
            updatedAt=session.updated_at.isoformat() if session.updated_at else None,
        )


class MessageVO(BaseModel):
    """消息 VO"""
    id: int
    sessionId: int
    role: str
    content: str
    msgType: str
    sources: Optional[List[Dict[str, Any]]] = None
    toolCalls: Optional[List[Dict[str, Any]]] = None
    seq: int
    createdAt: Optional[str] = None

    @classmethod
    def from_orm(cls, message: AgentMessage) -> "MessageVO":
        return cls(
            id=message.id,
            sessionId=message.session_id,
            role=message.role.value if message.role else MessageRole.USER.value,
            content=message.content or "",
            msgType=message.msg_type.value if message.msg_type else MessageType.TEXT.value,
            sources=message.sources,
            toolCalls=message.tool_calls,
            seq=message.seq,
            createdAt=message.created_at.isoformat() if message.created_at else None,
        )


class SessionListVO(Page[SessionVO]):
    """会话列表 VO（分页）"""
    pass


class MessageListVO(Page[MessageVO]):
    """消息列表 VO（分页）"""
    pass


__all__ = [
    "ChatRequest",
    "SessionListRequest",
    "SessionVO",
    "MessageVO",
    "SessionListVO",
    "MessageListVO",
]
