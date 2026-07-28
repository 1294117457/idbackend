"""意图分类节点"""
import json
import re
from typing import Any, Dict, Literal

from pydantic import BaseModel, Field

from src.agent.state import AgentState
from src.agent.prompts.classify_prompt import INTENT_CLASSIFY_PROMPT
from src.infra.ai.model import get_chat_model


class IntentOutput(BaseModel):
    """Classify 节点的结构化输出"""
    intent: Literal["chat", "consult", "apply"] = Field(
        description="用户意图：chat=闲聊 | consult=政策咨询 | apply=资助申请"
    )


async def classify_node(state: AgentState) -> Dict[str, Any]:
    """
    意图分类节点

    接收用户最新消息，使用 LLM 判断意图（结构化输出）
    """
    messages = state.get("messages", [])
    if not messages:
        return {"intent": "chat"}

    last_message = messages[-1]
    user_content = last_message.get("content", "")

    if not user_content:
        return {"intent": "chat"}

    prompt = INTENT_CLASSIFY_PROMPT.format(content=user_content)

    llm = get_chat_model()
    response: IntentOutput = await llm.with_structured_output(IntentOutput).ainvoke(prompt)
    return {"intent": response.intent}


async def classify_node_with_fallback(state: AgentState) -> Dict[str, Any]:
    """
    意图分类节点 - 带 markdown 兼容

    先用标准 structured_output，失败后降级为手动解析（兼容 LLM 返回 ```json``` 包裹的情况）。
    """
    messages = state.get("messages", [])
    if not messages:
        return {"intent": "chat"}

    last_message = messages[-1]
    user_content = last_message.get("content", "")

    if not user_content:
        return {"intent": "chat"}

    prompt = INTENT_CLASSIFY_PROMPT.format(content=user_content)

    llm = get_chat_model()
    try:
        response: IntentOutput = await llm.with_structured_output(IntentOutput).ainvoke(prompt)
        return {"intent": response.intent}
    except Exception:
        pass

    raw = (await llm.ainvoke(prompt)).content
    raw_str = str(raw).strip()

    fence_pattern = re.compile(r"^```(?:json)?\s*\n?|```\s*$", re.IGNORECASE | re.DOTALL)
    cleaned = fence_pattern.sub("", raw_str).strip()

    try:
        data = json.loads(cleaned)
        intent = data.get("intent", "chat")
        if intent not in ("chat", "consult", "apply"):
            intent = "chat"
        return {"intent": intent}
    except Exception:
        return {"intent": "chat"}