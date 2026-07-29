"""Agent 模块

LangGraph Agent 实现：
- 意图分类 (classify)
- 闲聊 (chat)
"""
from .state import AgentState, Message
from .graph.builder import (
    # 新版简化 API
    get_compiled_graph,
    create_graph,
    # 旧版兼容
    AgentGraph,
    get_agent_graph,
    GraphConfig,
)

__all__ = [
    # State
    "AgentState",
    "Message",
    # 新版简化 API（推荐）
    "get_compiled_graph",
    "create_graph",
    # 旧版兼容
    "AgentGraph",
    "get_agent_graph",
    "GraphConfig",
]