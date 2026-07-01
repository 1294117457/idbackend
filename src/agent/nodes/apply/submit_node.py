"""提交申请节点"""
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from agent.state import MainState


async def submit_node(state: MainState) -> Dict[str, Any]:
    """提交申请"""
    user_id = state.get("user_id")
    messages = state.get("messages", [])

    # TODO: 调用 ApplicationService
    return {
        "status": "pending_confirm",
        "messages": messages + [{
            "role": "assistant",
            "content": "好的，我来帮您提交申请。请问您确定要提交吗？"
        }],
    }
