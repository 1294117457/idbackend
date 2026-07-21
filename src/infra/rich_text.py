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
