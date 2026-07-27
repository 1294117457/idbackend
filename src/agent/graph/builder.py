"""LangGraph Agent Builder

支持节点：classify / chat
"""
from typing import Literal, Optional
from dataclasses import dataclass

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Checkpointer

from agent.state import AgentState
from agent.nodes.classify import classify_node
from agent.nodes.chat import chat_node


@dataclass
class GraphConfig:
    """图配置"""
    checkpointer: Optional[Checkpointer] = None


def create_agent_graph(config: Optional[GraphConfig] = None) -> StateGraph:
    """
    创建 Agent 图

    流程：
    classify → chat → END
    """
    graph = StateGraph(AgentState)

    # 添加节点
    graph.add_node("classify", classify_node)
    graph.add_node("chat", chat_node)

    # 设置入口
    graph.set_entry_point("classify")

    # 条件路由：classify → chat
    def route_after_classify(state: AgentState) -> Literal["chat", END]:
        intent = state.get("intent")
        if intent == "chat":
            return "chat"
        return END

    graph.add_conditional_edges(
        "classify",
        route_after_classify,
        {
            "chat": "chat",
        }
    )

    # chat 结束后 → END
    graph.add_edge("chat", END)

    cfg = config or GraphConfig()

    if cfg.checkpointer:
        return graph.compile(checkpointer=cfg.checkpointer)

    return graph.compile()


class AgentGraph:
    """Agent 图管理器"""

    def __init__(self, config: Optional[GraphConfig] = None):
        self.config = config
        self._graph = None

    @property
    def graph(self):
        if self._graph is None:
            self._graph = create_agent_graph(self.config)
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


# 全局单例
_agent_graph: Optional[AgentGraph] = None


def get_agent_graph(config: Optional[GraphConfig] = None) -> AgentGraph:
    """获取 AgentGraph 单例"""
    global _agent_graph
    if _agent_graph is None or config is not None:
        _agent_graph = AgentGraph(config)
    return _agent_graph


def create_checkpointer(connection_string: str) -> PostgresSaver:
    """便捷方法：创建 Checkpointer"""
    return PostgresSaver.from_conn_string(connection_string)