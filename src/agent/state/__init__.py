"""LangGraph 状态定义

State 设计原则：
- 生命周期：随 Graph 执行，在节点间流转，流程结束后释放
- 使用 Annotated 定义 reducer，实现消息追加而非替换
"""
from typing import TypedDict, Annotated, List, Optional
from operator import add


class Message(TypedDict):
    """消息结构"""
    role: str  # user / assistant / system
    content: str
    metadata: Optional[dict] = None


class AgentState(TypedDict):
    """主状态 - 用于 Classify + Chat 流程"""

    # ===== 对话历史 =====
    # 使用 add reducer：返回的 messages 会追加到现有列表
    messages: Annotated[List[Message], add]

    # ===== 用户信息 =====
    user_id: int
    session_id: str

    # ===== 意图路由 =====
    intent: Annotated[Optional[str], None]  # chat / consult / apply ...

    # ===== 生成的回复 =====
    generated_text: Annotated[str, ""]