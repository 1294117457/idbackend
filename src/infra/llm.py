"""LLM / Embedding 模型初始化

基于 LangChain 的 OpenAI 兼容接口，支持：
- Chat 模型（智谱 GLM-4、通义千问、SiliconFlow 等）
- Embedding 模型（SiliconFlow 等）

用途：
- Chat 模型：Agent 对话、RAG 生成答案
- Embedding 模型：生成向量用于检索
"""

from typing import List, Optional

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from src.infra.config import get_settings

# ─────────────────────────────────────────────────────────────────────────────
# 模型单例缓存
# ─────────────────────────────────────────────────────────────────────────────

_chat_model: Optional[ChatOpenAI] = None
_embedding_model: Optional[OpenAIEmbeddings] = None


def get_chat_model() -> ChatOpenAI:
    """获取 Chat 模型单例（用于 Agent 对话、RAG 生成）"""
    global _chat_model
    if _chat_model is None:
        settings = get_settings()
        _chat_model = ChatOpenAI(
            model=settings.LLM_CHAT_MODEL,
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
            temperature=0.7,
            timeout=60.0,
        )
    return _chat_model


def get_embedding_model() -> OpenAIEmbeddings:
    """获取 Embedding 模型单例（用于生成向量）"""
    global _embedding_model
    if _embedding_model is None:
        settings = get_settings()
        _embedding_model = OpenAIEmbeddings(
            model=settings.EMBEDDING_MODEL,
            api_key=settings.EMBEDDING_API_KEY,
            base_url=settings.EMBEDDING_BASE_URL,
        )
    return _embedding_model


# ─────────────────────────────────────────────────────────────────────────────
# 便捷方法（Embedding 批量调用）
# ─────────────────────────────────────────────────────────────────────────────

async def embed_text(text: str) -> List[float]:
    """生成单个文本的向量"""
    model = get_embedding_model()
    return await model.aembed_query(text)


async def embed_texts(texts: List[str]) -> List[List[float]]:
    """批量生成多个文本的向量"""
    model = get_embedding_model()
    return await model.aembed_documents(texts)
