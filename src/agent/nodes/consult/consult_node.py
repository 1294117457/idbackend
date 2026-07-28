"""政策咨询节点"""
import logging
from typing import Dict, Any, List

from src.agent.state import AgentState
from src.agent.nodes.consult.consult_prompt import CONSULT_PROMPT
from src.infra.ai.model import get_chat_model

logger = logging.getLogger(__name__)


async def consult_node(state: AgentState) -> Dict[str, Any]:
    """
    政策咨询节点

    流程：
    1. 提取用户最新输入
    2. 调用 rrf_search 检索政策知识库
    3. 组装 RAG 上下文
    4. 调用 LLM 生成回答
    5. 返回结果

    Args:
        state: Graph 当前状态

    Returns:
        {
            "generated_text": LLM 生成的回答,
            "sources": 检索来源列表,
            "rag_context": 原始检索上下文,
        }
    """
    from src.services.embedding_service import get_embedding_service
    from src.infra.database import get_db_context
    from src.infra.config import get_rag_config

    messages = state.get("messages", [])
    if not messages:
        logger.warning("[consult_node] 消息列表为空")
        return {
            "generated_text": "未收到有效输入",
            "sources": [],
            "rag_context": "",
        }

    # 1. 提取用户输入
    user_content = messages[-1].get("content", "")
    if not user_content:
        logger.warning("[consult_node] 用户输入为空")
        return {
            "generated_text": "未收到有效输入",
            "sources": [],
            "rag_context": "",
        }

    logger.info(f"[consult_node] 用户输入: {user_content[:50]}...")

    # 2. 获取 RAG 配置
    rag_cfg = get_rag_config()
    top_k = rag_cfg.get("top_k", 5)

    # 3. RAG 检索（在独立事务中）
    try:
        async with get_db_context() as db:
            embedding_svc = get_embedding_service()
            fusion_result = await embedding_svc.rrf_search(
                db,
                query=user_content,
                category="policy",
                top_k=top_k,
            )
        logger.info(f"[consult_node] RAG 检索完成，命中 {len(fusion_result.hits)} 条")
    except Exception as e:
        logger.error(f"[consult_node] RAG 检索失败: {e}")
        return {
            "generated_text": "检索服务暂时不可用，请稍后再试",
            "sources": [],
            "rag_context": "",
        }

    # 4. 组装检索上下文
    rag_context = _format_rag_context(fusion_result.hits)

    # 5. 调用 LLM
    prompt = CONSULT_PROMPT.format(
        user_input=user_content,
        rag_context=rag_context,
    )

    try:
        llm = get_chat_model()
        response = await llm.ainvoke(prompt)
        generated_text = response.content
        logger.info(f"[consult_node] LLM 生成回答，长度={len(generated_text)}")
    except Exception as e:
        logger.error(f"[consult_node] LLM 调用失败: {e}")
        return {
            "generated_text": "生成回答失败，请稍后再试",
            "sources": [],
            "rag_context": rag_context,
        }

    # 6. 返回结果
    return {
        "generated_text": generated_text,
        "sources": [h.get("source_id", "") for h in fusion_result.hits],
        "rag_context": rag_context,
    }


def _format_rag_context(hits: List[dict]) -> str:
    """格式化检索结果为上下文"""
    if not hits:
        return "（未检索到相关政策信息）"

    parts = []
    for i, hit in enumerate(hits, 1):
        title = hit.get("title", "未知来源")
        content = hit.get("content", "")
        parts.append(f"[{i}] {title}\n{content}\n")

    return "\n".join(parts)
