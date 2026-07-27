"""LLM / Embedding 模型初始化

基于 LangChain 的 OpenAI 兼容接口，支持：
- Chat 模型（智谱 GLM-4、通义千问、SiliconFlow 等）
- Embedding 模型（SiliconFlow 等）

用途：
- Chat 模型：Agent 对话、RAG 生成答案
- Embedding 模型：生成向量用于检索

配置优先级：DB (system_config 表) > .env
"""

from typing import List, Optional

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from src.infra.config import get_llm_config, get_embed_config


# ─────────────────────────────────────────────────────────────────────────────
# 模型单例缓存（每次调用时检查配置是否变化，变化则重建）
# ─────────────────────────────────────────────────────────────────────────────

_chat_model: Optional[ChatOpenAI] = None
_embedding_model: Optional[OpenAIEmbeddings] = None
_cached_llm_config: Optional[dict] = None
_cached_embed_config: Optional[dict] = None


def get_chat_model() -> ChatOpenAI:
    """获取 Chat 模型单例（用于 Agent 对话、RAG 生成）

    配置变化时自动重建实例。
    """
    global _chat_model, _cached_llm_config
    cfg = get_llm_config()

    should_rebuild = (
        _chat_model is None
        or _cached_llm_config is None
        or cfg.get("chat_model") != _cached_llm_config.get("chat_model")
        or cfg.get("base_url") != _cached_llm_config.get("base_url")
    )

    if should_rebuild:
        _chat_model = ChatOpenAI(
            model=cfg.get("chat_model", "gpt-4o"),
            api_key=cfg.get("api_key") or "",
            base_url=cfg.get("base_url"),
            temperature=0.7,
            timeout=60.0,
        )
        _cached_llm_config = dict(cfg)

    return _chat_model


def get_embedding_model() -> OpenAIEmbeddings:
    """获取 Embedding 模型单例（用于生成向量）

    配置变化时自动重建实例。
    """
    global _embedding_model, _cached_embed_config
    cfg = get_embed_config()

    should_rebuild = (
        _embedding_model is None
        or _cached_embed_config is None
        or cfg.get("model") != _cached_embed_config.get("model")
        or cfg.get("base_url") != _cached_embed_config.get("base_url")
    )

    if should_rebuild:
        _embedding_model = OpenAIEmbeddings(
            model=cfg.get("model", "text-embedding-3-small"),
            api_key=cfg.get("api_key") or "",
            base_url=cfg.get("base_url"),
            dimensions=cfg.get("dim"),
        )
        _cached_embed_config = dict(cfg)

    return _embedding_model


# ─────────────────────────────────────────────────────────────────────────────
# 便捷方法（Embedding 批量调用）
# ─────────────────────────────────────────────────────────────────────────────

async def embed_text(text: str) -> List[float]:
    """生成单个文本的向量"""
    if not text or not text.strip():
        raise ValueError("embed_text: text 不能为空")
    model = get_embedding_model()
    return await model.aembed_query(text)


async def embed_texts(texts: List[str]) -> List[List[float]]:
    """批量生成多个文本的向量"""
    if not texts:
        return []
    model = get_embedding_model()
    return await model.aembed_documents(texts)
