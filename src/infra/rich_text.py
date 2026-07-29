"""RichText - 富文本纯逻辑工具

纯正则解析，不依赖基础设施。
"""
import re
from typing import Optional


# 占位符正则: <img src="editor://temp/{filename}" /> 或 <img src="editor://{entity}/{id}/{filename}" />
# editor:// 后面直接跟路径（temp 或 entity/id），无 object/
_IMG_SRC_PATTERN = re.compile(
    r"""(<img\b[^>]*?\bsrc=["'])editor://([^"'\s>]+)(["'][^>]*?/?>)""",
    flags=re.IGNORECASE,
)
# src="" 的 <img> 节点清理
_EMPTY_IMG_PATTERN = re.compile(
    r"""<img\b[^>]*?\bsrc=["']["'][^>]*?/?>""",
    flags=re.IGNORECASE,
)


class RichText:
    """富文本纯逻辑工具"""

    @staticmethod
    def extract_filenames(html: Optional[str]) -> list[str]:
        """从 HTML 提取所有占位符路径（去重）。
        
        返回完整路径，如 "temp/abc.png" 或 "template/123/abc.png"。
        """
        if not html:
            return []
        return list(set(match.group(2) for match in _IMG_SRC_PATTERN.finditer(html)))

    @staticmethod
    def build_storage_key(entity_type: str, entity_id: int, filename: str) -> str:
        """构建 MinIO object_key。"""
        return f"editor/{entity_type}/{entity_id}/{filename}"

    @staticmethod
    def replace_in_html(html: str, url_map: dict[str, str]) -> str:
        """用预签名 URL 替换 HTML 中的占位符。

        url_map 的 key 是完整路径（如 "temp/abc.png"），
        匹配占位符 "editor://temp/abc.png"。
        """
        def _sub(match):
            prefix = match.group(1)
            path = match.group(2)
            suffix = match.group(3)
            return f"{prefix}{url_map.get(path, '')}{suffix}"

        replaced = _IMG_SRC_PATTERN.sub(_sub, html)
        replaced = _EMPTY_IMG_PATTERN.sub("", replaced)
        return replaced

    @staticmethod
    def get_storage_prefix(entity_type: str, entity_id: int) -> str:
        """获取 MinIO 存储前缀，用于删除。"""
        return f"editor/{entity_type}/{entity_id}"

    @staticmethod
    def strip_html(html: Optional[str]) -> str:
        """去除 HTML 标签和图片引用，返回纯文本。

        用于生成向量检索用的纯文本内容。

        流程：
        1. _IMG_SRC_PATTERN 已经匹配 <img ... src="editor://..."> 整个标签
           （包括 <img> 开头到 /> 结尾），因此图片引用整体被删除。
        2. 去除剩余 HTML 标签（<p>、<strong> 等）
        3. 规范化空白（多个空白字符 → 单个空格，首尾 strip）
        """
        if not html:
            return ""
        # 1. 去除 <img> 标签（含 editor:// 占位符）
        text = _IMG_SRC_PATTERN.sub("", html)
        # 2. 去除剩余 HTML 标签
        text = re.sub(r"<[^>]+>", " ", text)
        # 3. 规范化空白
        text = re.sub(r"\s+", " ", text).strip()
        return text
