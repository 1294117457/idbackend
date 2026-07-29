"""路由函数

定义节点间的条件路由逻辑
"""
from typing import Literal

from src.agent.state import AgentState


def route_after_classify(state: AgentState) -> Literal["chat", "consult", "__end__"]:
    """
    Classify 节点后的路由

    Args:
        state: Graph 当前状态

    Returns:
        "chat" → 进入 chat 节点
        "consult" → 进入 consult 节点
        "__end__" → 流程结束（暂不支持的意图）
    """
    intent = state.get("intent", "chat")

    if intent == "chat":
        return "chat"
    if intent == "consult":
        return "consult"

    # 暂时不支持其他意图，直接结束
    return "__end__"


def route_after_consult(state: AgentState) -> Literal["__end__"]:
    """
    Consult 节点后的路由

    当前阶段：直接结束
    后续扩展：用户表达申请意愿时路由到 apply 节点

    Args:
        state: Graph 当前状态

    Returns:
        "__end__" → 流程结束
    """
    # TODO: 后续可扩展为 LLM 判断用户是否需要申请
    # 方式1: 前端通过 interrupt 机制标记
    # 方式2: LLM 在回答末尾询问"是否需要申请"
    return "__end__"
