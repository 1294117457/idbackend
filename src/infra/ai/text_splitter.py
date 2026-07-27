"""文本切块工具

基于 LangChain 的 RecursiveCharacterTextSplitter 实现递归字符切分。
按语义边界（段落 → 换行 → 句号 → 逗号 → 字符）递归拆分文本，
确保不会在句子中间切断。

使用：
    from src.infra.ai.text_splitter import split_text

    chunks = split_text("很长的文档内容...", chunk_size=500, chunk_overlap=100)
"""

from typing import List, Optional

from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.infra.config import get_rag_config


# 中文优化的分隔符列表（优先级从高到低）
_CHINESE_SEPARATORS = [
    "\n\n",        # 空行（段落分隔）
    "\n",          # 换行
    "。",          # 中文句号
    "！",          # 中文感叹号
    "？",          # 中文问号
    "；",          # 中文分号
    ".",           # 英文句号
    "!",           # 英文感叹号
    "?",           # 英文问号
    ";",           # 英文分号
    "，",          # 中文逗号
    ",",           # 英文逗号
    " ",           # 空格
    "",            # 单字符（保底）
]


_CHUNK_MIN_LENGTH = 50  # 最小 chunk 字符数，过短的无意义片段（封面/页眉/日期行）不入库


def split_text(
    text: str,
    *,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
    separators: Optional[List[str]] = None,
    min_length: Optional[int] = None,
) -> List[str]:
    """将文本按语义边界递归切分为多个 chunk。

    Args:
        text: 待切分的文本
        chunk_size: 每个 chunk 的目标大小（字符数），默认从 get_rag_config() 获取
        chunk_overlap: 相邻 chunk 的重叠字符数，默认从 get_rag_config() 获取
        separators: 自定义分隔符列表，默认使用中文优化的分隔符
        min_length: 最小 chunk 字符数，默认 _CHUNK_MIN_LENGTH（50）

    Returns:
        切分后的文本片段列表
    """
    if not text or not text.strip():
        return []

    rag = get_rag_config()
    size = chunk_size if chunk_size is not None else rag.get("chunk_size", 400)
    overlap = chunk_overlap if chunk_overlap is not None else rag.get("chunk_overlap", 100)
    min_len = min_length if min_length is not None else _CHUNK_MIN_LENGTH

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=size,
        chunk_overlap=overlap,
        separators=separators or _CHINESE_SEPARATORS,
        length_function=len,
        is_separator_regex=False,
    )

    chunks = splitter.split_text(text)

    # 先过滤空白，再过滤过短 chunk（封面、页眉、日期行、孤立标题等）
    return [c for c in chunks if c.strip() and len(c) >= min_len]


def split_text_with_metadata(
    text: str,
    *,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
    source: Optional[str] = None,
) -> List[dict]:
    """切分文本并返回带元数据的 chunk 列表。

    Args:
        text: 待切分的文本
        chunk_size: 每个 chunk 的目标大小
        chunk_overlap: 重叠字符数
        source: 来源标识（如文件名）

    Returns:
        [{"content": "chunk内容", "chunk_index": 0, "source": "file.pdf"}, ...]
    """
    chunks = split_text(
        text,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    return [
        {
            "content": chunk,
            "chunk_index": idx,
            "total_chunks": len(chunks),
            "source": source,
        }
        for idx, chunk in enumerate(chunks)
    ]
