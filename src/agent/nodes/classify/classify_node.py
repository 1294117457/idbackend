"""意图分类节点"""
from typing import Dict, Any

from agent.state import AgentState
from agent.prompts.classify_prompt import INTENT_CLASSIFY_PROMPT
from src.infra.ai.model import get_chat_model


INTENT_OPTIONS = ["chat"]


async def classify_node(state: AgentState) -> Dict[str, Any]:
    """
    意图分类节点

    接收用户最新消息，使用 LLM 判断意图
    """
    messages = state.get("messages", [])
    if not messages:
        return {"intent": None}

    last_message = messages[-1]
    user_content = last_message.get("content", "")

    if not user_content:
        return {"intent": "chat"}

    prompt = INTENT_CLASSIFY_PROMPT.format(content=user_content)

    llm = get_chat_model()
    response = await llm.ainvoke(prompt)
    intent = response.content.strip().lower()

    if intent not in INTENT_OPTIONS:
        intent = "chat"

    return {"intent": intent}