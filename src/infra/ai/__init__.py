"""AI 工具包

包含：
- model: LLM/Embedding 模型初始化与调用
- text_splitter: 文本切块工具
- retrieval_processor: 检索命中结果分数处理
"""
from src.infra.ai.model import (
    get_chat_model,
    get_embedding_model,
    embed_text,
    embed_texts,
)
from src.infra.ai.text_splitter import split_text
from src.infra.ai.retrieval_processor import process_hits, fuse_hits

__all__ = [
    "get_chat_model",
    "get_embedding_model",
    "embed_text",
    "embed_texts",
    "split_text",
    "process_hits",
    "fuse_hits",
]
