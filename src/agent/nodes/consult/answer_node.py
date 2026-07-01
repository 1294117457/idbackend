"""回答用户咨询"""
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from agent.state import MainState


async def answer_node(state: MainState) -> Dict[str, Any]:
    """回答用户咨询"""
    messages = state.get("messages", [])
    if not messages:
        return {"result": {"message": "请描述您的问题"}}

    last_message = messages[-1]
    content = last_message.get("content", "")

    # TODO: 调用 RAG 检索
    answer = f"关于'{content}'，我来帮您查询..."

    return {
        "result": {"message": answer, "type": "consult"},
        "messages": messages + [{"role": "assistant", "content": answer}],
    }
