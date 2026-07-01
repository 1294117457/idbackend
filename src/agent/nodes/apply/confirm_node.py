"""确认申请节点"""
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from agent.state import MainState


async def confirm_node(state: MainState) -> Dict[str, Any]:
    """确认申请"""
    messages = state.get("messages", [])
    last_message = messages[-1] if messages else {}

    # TODO: 调用 ApplicationService 创建申请
    return {
        "status": "completed",
        "result": {"message": "申请已提交成功！"},
        "messages": messages + [{
            "role": "assistant",
            "content": "申请已提交成功！"
        }],
    }
