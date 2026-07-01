"""LangGraph Agent Builder"""
from typing import Optional, Callable
from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agent.state import MainState
from agent.nodes.classify import classify_node
from agent.nodes.consult import answer_node
from agent.nodes.apply import submit_node, confirm_node


def create_graph():
    """创建主图"""
    graph = StateGraph(MainState)

    # 添加节点
    graph.add_node("classify", classify_node)
    graph.add_node("consult", answer_node)
    graph.add_node("apply_submit", submit_node)
    graph.add_node("apply_confirm", confirm_node)

    # 设置入口
    graph.set_entry_point("classify")

    # 添加边
    graph.add_edge("classify", "consult", condition=lambda s: s.get("intent") == "consult")
    graph.add_edge("classify", "apply_submit", condition=lambda s: s.get("intent") == "apply")

    graph.add_edge("apply_submit", "apply_confirm")
    graph.add_edge("apply_confirm", END)

    return graph.compile()


class AgentGraph:
    """Agent 图管理器"""

    def __init__(self):
        self.graph = create_graph()

    async def invoke(self, messages: list, user_id: int, session_id: str):
        """同步调用"""
        result = await self.graph.ainvoke({
            "messages": messages,
            "user_id": user_id,
            "session_id": session_id,
        })
        return result

    async def stream(self, messages: list, user_id: int, session_id: str):
        """流式调用"""
        async for event in self.graph.astream({
            "messages": messages,
            "user_id": user_id,
            "session_id": session_id,
        }):
            yield event
