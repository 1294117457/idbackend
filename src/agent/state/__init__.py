"""LangGraph 状态定义"""
from typing import TypedDict, List, Optional, Any
from pydantic import BaseModel


class Message(TypedDict):
    """消息"""
    role: str  # user / assistant / system
    content: str
    metadata: Optional[dict] = None


class MainState(TypedDict):
    """主状态"""
    messages: List[Message]
    user_id: int
    session_id: str
    intent: Optional[str] = None
    result: Optional[dict] = None


class ApplyState(TypedDict):
    """申请流程状态"""
    messages: List[Message]
    user_id: int
    session_id: str
    template_id: Optional[int] = None
    rule_id: Optional[int] = None
    apply_input: Optional[float] = None
    proof_file_ids: Optional[List[int]] = None
    status: str = "in_progress"  # in_progress / completed / failed
    result: Optional[dict] = None


class ConsultState(TypedDict):
    """咨询状态"""
    messages: List[Message]
    user_id: int
    session_id: str
    query: str
    retrieved_docs: Optional[List[dict]] = None
    answer: Optional[str] = None
