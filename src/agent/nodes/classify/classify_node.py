"""意图分类节点"""
from typing import Dict, Any
from langchain_core.messages import HumanMessage

from agent.state import MainState


async def classify_node(state: MainState) -> Dict[str, Any]:
    """分类用户意图"""
    messages = state.get("messages", [])
    if not messages:
        return {"intent": None, "result": {"message": "请输入您的问题"}}

    last_message = messages[-1]
    content = last_message.get("content", "")

    # 简单的关键词分类
    consult_keywords = ["怎么", "如何", "规则", "政策", "是什么", "多少", "查询"]
    apply_keywords = ["申请", "加分", "提交", "要什么", "证明"]

    if any(k in content for k in consult_keywords):
        intent = "consult"
    elif any(k in content for k in apply_keywords):
        intent = "apply"
    else:
        intent = "consult"

    return {
        "intent": intent,
        "messages": messages + [{"role": "assistant", "content": f"我理解您想要{intent}"}],
    }
