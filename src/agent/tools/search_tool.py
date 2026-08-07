"""知识库检索 Tool

将 embedding_service.rrf_search 封装为 LangGraph Tool。
当前阶段：仅作为基础设施，不挂载到任何节点。
后续阶段：可被 ConsultNode / ApplyNode 用 bind_tools 方式调用，
由 LLM 决策何时检索。
"""
from langchain_core.tools import tool

from src.infra.database import get_db_context
from src.services.embedding_service import get_embedding_service


@tool
async def search_knowledge_base(
    query: str,
    category: str = "policy",
    top_k: int = 5,
) -> str:
    """检索政策知识库（基于 RRF 混合检索：向量 + BM25）。
    
    Args:
        query: 检索关键词或问题
        category: 检索分类（policy / faq 等）
        top_k: 返回条数
    
    Returns:
        格式化的检索结果字符串，便于 LLM 阅读
    """
    try:
        async with get_db_context() as db:
            svc = get_embedding_service()
            result = await svc.rrf_search(db, query, category=category, top_k=top_k)
    except Exception:
        # Tool 异常应为业务可读字符串
        return "（检索服务暂时不可用）"
    
    if not result.hits:
        return "（未检索到相关政策信息）"
    
    parts = []
    for i, hit in enumerate(result.hits, 1):
        title = hit.get("title", "未知来源")
        content = hit.get("content", "")
        parts.append(f"[{i}] {title}\n{content}")
    
    return "\n\n".join(parts)
