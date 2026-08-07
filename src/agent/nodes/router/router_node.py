"""Router 节点 - 意图识别 + 路由"""
import json
import re
from typing import Any, Dict, Literal

from pydantic import BaseModel, Field

from src.agent.state import AgentState
from src.agent.prompts.router_prompt import INTENT_CLASSIFY_PROMPT
from src.infra.ai.model import get_chat_model


class IntentOutput(BaseModel):
    """意图识别结构化输出"""
    intent: Literal["chat", "consult", "apply"] = Field(
        description="用户意图：chat=闲聊 | consult=政策咨询 | apply=资助申请"
    )


# markdown 包裹正则（兼容 ```json ... ``` 和 ``` ... ``` 两种格式）
_FENCE_PATTERN = re.compile(
    r"^```(?:json)?\s*\n?|```\s*$",
    re.IGNORECASE | re.DOTALL,
)


async def router_node(state: AgentState) -> Dict[str, Any]:
    """意图识别节点
    
    流程：
    1. 提取用户最新消息
    2. 优先使用 structured_output
    3. 失败时降级为手动 JSON 解析（兼容 markdown 包裹）
    
    Args:
        state: Graph 当前状态
    
    Returns:
        {"intent": "chat" | "consult" | "apply"}
    """
    messages = state.get("messages", [])
    if not messages:
        return {"intent": "chat"}
    
    user_content = messages[-1].get("content", "")
    if not user_content:
        return {"intent": "chat"}
    
    prompt = INTENT_CLASSIFY_PROMPT.format(content=user_content)
    llm = get_chat_model()
    
    # 路径 1: structured_output
    try:
        response: IntentOutput = await llm.with_structured_output(IntentOutput).ainvoke(prompt)
        return {"intent": response.intent}
    except Exception as e:
        # 进入降级路径，不直接报错
        pass
    
    # 路径 2: 手动解析（兼容 markdown 包裹）
    raw = (await llm.ainvoke(prompt)).content
    cleaned = _FENCE_PATTERN.sub("", str(raw)).strip()
    
    try:
        data = json.loads(cleaned)
        intent = data.get("intent", "chat")
        if intent not in ("chat", "consult", "apply"):
            intent = "chat"
        return {"intent": intent}
    except Exception:
        # 终极兜底
        return {"intent": "chat"}
