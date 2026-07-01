"""Agent 服务"""
from typing import Optional, AsyncGenerator, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from agent.graph.builder import AgentGraph
from agent.tools import (
    get_user_info_tool,
    get_user_scores_tool,
    get_templates_tool,
    get_template_rules_tool,
    create_application_tool,
    get_user_applications_tool,
)


class AgentService:
    """Agent 服务"""

    def __init__(self):
        self.graph = AgentGraph()

    async def invoke(
        self,
        message: str,
        user_id: int,
        session_id: str = "default",
        db: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """同步调用"""
        messages = [{"role": "user", "content": message}]

        result = await self.graph.invoke(messages, user_id, session_id)
        return result.get("result", {})

    async def stream(
        self,
        message: str,
        user_id: int,
        session_id: str = "default",
        db: Optional[AsyncSession] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """流式调用"""
        messages = [{"role": "user", "content": message}]

        async for event in self.graph.stream(messages, user_id, session_id):
            if "messages" in event:
                last_msg = event["messages"][-1]
                yield {
                    "type": "message",
                    "content": last_msg.get("content", ""),
                }
            elif "result" in event:
                yield {
                    "type": "result",
                    "data": event["result"],
                }

    async def resume(
        self,
        session_id: str,
        supplement: str,
        user_id: int,
        db: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """恢复对话"""
        # TODO: 实现对话恢复
        return await self.invoke(supplement, user_id, session_id, db)
