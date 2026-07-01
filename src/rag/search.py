"""向量搜索"""
from typing import List


async def search_documents(
    query: str,
    top_k: int = 5,
) -> List[dict]:
    """搜索相关文档"""
    # TODO: 实现向量搜索
    return [
        {
            "title": "示例文档",
            "content": "这是相关的文档内容...",
            "score": 0.95,
        }
    ]
