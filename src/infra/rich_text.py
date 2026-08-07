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
# 兜底：从脏数据中识别"残留的预签名 URL"，提取 path
# 匹配：
#   /{bucket}/editor/{path}?X-Amz-...
#   /editor/{path}?X-Amz-...
#   /{bucket}/editor/{path}
#   /editor/{path}
# 全部截到第一个 ? / " / ' / 空白为止
_DIRTY_SRC_PATTERN = re.compile(
    r"""(src=["'])(?:/[^/"'\s]+)?/editor/([^"'\s?>]+)(?:\?[^"']*)?["']""",
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
    def extract_paths_from_dirty_urls(html: Optional[str]) -> list[str]:
        """兜底：从 DB 里残留的预签名 URL 中提取 ObjectKey 路径。

        用于兼容历史脏数据：DB 里直接存了 /{bucket}/editor/...?X-Amz-...
        却没有经过 process_html 转占位符的场景。修复后这些脏 URL 应当被
        业务侧脚本清理；这里是渲染时的最后一道防线。

        返回值是完整 key（不含 "editor/" 前缀），例如
        "template/39/1fce624e69f3417b9af6b726600c8b64.png"。

        行为与 extract_filenames 互不重叠：
        - extract_filenames 匹配 editor://...
        - 本方法匹配 /editor/... 或 /{bucket}/editor/...
        """
        if not html:
            return []
        return list(set(m.group(2) for m in _DIRTY_SRC_PATTERN.finditer(html)))

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
