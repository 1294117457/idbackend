"""聊天节点"""
from typing import Dict, Any
from langchain_core.messages import HumanMessage, SystemMessage

from agent.state import AgentState
from src.infra.ai.model import get_chat_model


CHAT_SYSTEM_PROMPT = """你是一个友好的政策咨询助手。

要求：
1. 友好、礼貌地与用户交流
2. 简洁回答，不要过于冗长
3. 如果涉及政策问题，可以建议用户使用咨询功能
4. 不确定的问题，诚实告知
"""


async def chat_node(state: AgentState) -> Dict[str, Any]:
    """
    聊天节点

    直接使用 LLM 生成回复，无需 RAG
    """
    messages = state.get("messages", [])
    
    lc_messages = [SystemMessage(content=CHAT_SYSTEM_PROMPT)]
    
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "user":
            lc_messages.append(HumanMessage(content=content))
        elif role == "assistant":
            lc_messages.append(AIMessage(content=content))

    llm = get_chat_model()
    response = await llm.ainvoke(lc_messages)
    generated_text = response.content

    return {"generated_text": generated_text}
