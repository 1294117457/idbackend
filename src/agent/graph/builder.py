"""LangGraph Agent Builder

支持节点：classify / chat
"""
from typing import Literal, Optional
from dataclasses import dataclass

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from src.agent.state import AgentState
from src.agent.nodes.classify import classify_node_with_fallback as classify_node
from src.agent.nodes.chat import chat_node
from src.agent.nodes.consult import consult_node
from src.agent.graph.routers import route_after_classify, route_after_consult


def create_graph() -> StateGraph:
    """
    创建 Agent Graph

    流程：classify → router → chat/consult → END
    """
    graph = StateGraph(AgentState)

    # 添加节点
    graph.add_node("classify", classify_node)
    graph.add_node("chat", chat_node)
    graph.add_node("consult", consult_node)

    # 设置入口
    graph.set_entry_point("classify")

    # 条件路由：classify → chat / consult
    graph.add_conditional_edges(
        "classify",
        route_after_classify,
        {
            "chat": "chat",
            "consult": "consult",
        }
    )

    # consult 结束后 → END
    graph.add_edge("consult", END)

    # chat 结束后 → END
    graph.add_edge("chat", END)

    return graph.compile()


# ─────────────────────────────────────────────────────────────────────────────
# 全局单例 Graph
# ─────────────────────────────────────────────────────────────────────────────

_compiled_graph = None


def get_compiled_graph() -> StateGraph:
    """获取编译后的 Graph 单例

    使用单例避免重复编译，线程安全
    """
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = create_graph()
    return _compiled_graph


# ─────────────────────────────────────────────────────────────────────────────
# 保留旧版 AgentGraph（向后兼容，后续可删除）
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class GraphConfig:
    """图配置"""
    checkpointer: Optional[MemorySaver] = None


def create_agent_graph(config: Optional[GraphConfig] = None) -> StateGraph:
    """
    创建 Agent 图（兼容旧版）

    流程：
    classify → chat → END
    """
    return create_graph()


class AgentGraph:
    """Agent 图管理器（兼容旧版，后续可删除）"""

    def __init__(self, config: Optional[GraphConfig] = None):
        self.config = config
        self._graph = None

    @property
    def graph(self):
        if self._graph is None:
            self._graph = create_graph()
        return self._graph

    async def invoke(
        self,
        messages: list,
        user_id: int,
        session_id: str,
        config: Optional[dict] = None,
    ) -> dict:
        """同步调用"""
        state = {
            "messages": messages,
            "user_id": user_id,
            "session_id": session_id,
        }
        result = await self.graph.ainvoke(state, config=config)
        return result

    async def stream(
        self,
        messages: list,
        user_id: int,
        session_id: str,
        config: Optional[dict] = None,
    ):
        """流式调用"""
        state = {
            "messages": messages,
            "user_id": user_id,
            "session_id": session_id,
        }
        async for event in self.graph.astream(state, config=config):
            yield event


# 全局单例（兼容旧版）
_agent_graph: Optional[AgentGraph] = None


def get_agent_graph(config: Optional[GraphConfig] = None) -> AgentGraph:
    """获取 AgentGraph 单例（兼容旧版）"""
    global _agent_graph
    if _agent_graph is None or config is not None:
        _agent_graph = AgentGraph(config)
    return _agent_graph