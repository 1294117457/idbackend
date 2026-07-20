"""富文本占位协议 → 预签名 URL 替换

设计要点：
- 占位协议：<img src="editor://object/{key}" />
  - 编辑器写入 → DB 原样存储
  - 后端读取前：解析出 object_name → 直接调 storage 签 URL（不查 file_metadata）
- 不写 file_metadata：富文本图片是独立通道，仅靠 key 关联
- 鉴权：仅过滤 editor/ 前缀，避免其他类别的 key 被盗用
"""
import re
from typing import Iterable, List, Mapping, Optional, Set

from sqlalchemy.ext.asyncio import AsyncSession

from src.infra.storage import Storage


# 占位协议的正则
_OBJECT_PATTERN = re.compile(r"editor://object/([^\"'\s>]+)")
# <img ... src="editor://object/{key}" ...> 整段匹配（贪婪到下一个 " 或 '）
_IMG_SRC_PATTERN = re.compile(
    r"""(<img\b[^>]*?\bsrc=["'])editor://object/([^"'\s>]+)(["'][^>]*?/?>)""",
    flags=re.IGNORECASE,
)
# src="" 的 <img> 节点清理（包含无值/单引号/双引号三种形态）
_EMPTY_IMG_PATTERN = re.compile(
    r"""<img\b[^>]*?\bsrc=["']["'][^>]*?/?>""",
    flags=re.IGNORECASE,
)

# 默认签名有效期（1 小时）
_DEFAULT_EXPIRY_SECONDS = 3600

# 仅允许的前缀（避免被滥用签其它类别的对象）
_EDITOR_PREFIX = "editor/"


class RichTextImageProcessor:
    """占位 → 预签名 URL 替换器（仅依赖 Storage，不查 DB）"""

    def __init__(self, db: AsyncSession, storage: Storage):
        self._db = db
        self._storage = storage

    # ============================================================
    # 占位提取
    # ============================================================

    @staticmethod
    def extract_object_names(html: Optional[str]) -> Set[str]:
        """提取 HTML 中所有占位的 object_name（已去重）。空 HTML 返回空集合。"""
        if not html:
            return set()
        return {m.group(1) for m in _OBJECT_PATTERN.finditer(html)}

    # ============================================================
    # 批量签名 URL（按 object key，不查 DB）
    # ============================================================

    def build_signed_url_map(
        self,
        keys: Iterable[str],
        *,
        expiry_seconds: int = _DEFAULT_EXPIRY_SECONDS,
    ) -> Mapping[str, str]:
        """批量：object key → 预签名 URL

        规则：
        - 仅允许 editor/ 前缀的 key（其它前缀直接跳过，避免越权签）
        - 不查 DB、不校验 owner（key 足够长难猜；业务决定：富文本图片对登录用户开放）
        - 每个 key 单独 generate_presigned_url（MinIO 本地 HMAC，< 1ms/次）
        """
        safe_keys: Set[str] = set()
        for k in keys:
            if not isinstance(k, str) or not k.startswith(_EDITOR_PREFIX):
                continue
            # editor/ 后面必须有内容（防裸 "editor/"）
            if len(k) <= len(_EDITOR_PREFIX):
                continue
            safe_keys.add(k)
        if not safe_keys:
            return {}

        result: dict[str, str] = {}
        for k in safe_keys:
            result[k] = self._storage.get_download_url(
                k,
                original_name=None,
                expiry=expiry_seconds,
                force_attachment=False,  # 渲染用，不强制下载
            )
        return result

    # ============================================================
    # 替换入口
    # ============================================================

    async def replace(self, html: Optional[str]) -> Optional[str]:
        """单条 HTML 替换（详情场景）。无占位直接返回原值。"""
        if not html:
            return html
        keys = self.extract_object_names(html)
        if not keys:
            return html
        url_map = self.build_signed_url_map(keys)
        return _do_replace(html, url_map)

    async def replace_batch(
        self,
        htmls: List[Optional[str]],
    ) -> List[Optional[str]]:
        """批量替换（列表场景）：先 union 所有 key → 单签 → 分发"""
        all_keys: Set[str] = set()
        for h in htmls:
            all_keys.update(self.extract_object_names(h))
        if not all_keys:
            return htmls
        url_map = self.build_signed_url_map(all_keys)
        return [(_do_replace(h, url_map) if h else h) for h in htmls]

    # ============================================================
    # ORM 对象的便捷方法（template_service 专用）
    # ============================================================

    async def replace_one_on_model(self, template) -> None:
        """就地改 ORM 对象的 description 字段（in-place，不返回值）"""
        if template.description:
            template.description = await self.replace(template.description)

    async def replace_batch_on_models(self, templates: Iterable) -> None:
        """批量就地改 ORM 对象"""
        objs = list(templates)
        htmls = [t.description for t in objs]
        replaced = await self.replace_batch(htmls)
        for t, h in zip(objs, replaced):
            t.description = h


# ============================================================
# 内部辅助（纯函数，单测友好）
# ============================================================

def _do_replace(html: str, url_map: Mapping[str, str]) -> str:
    """就地替换 <img src="editor://object/{key}"> 的 src。

    - 命中 url_map → 替换为对应签名 URL
    - 未命中（key 不合法或非 editor/ 前缀） → src 置空
    - 收尾：清理所有 src="" 的 <img> 节点，避免破图占位
    """
    def _sub_src(m: re.Match) -> str:
        key = m.group(2)
        url = url_map.get(key, "")
        # m.group(1) = '<img ... src="'
        # m.group(2) = 'editor/abc.png'
        # m.group(3) = '" ... />'
        return f"{m.group(1)}{url}{m.group(3)}"

    replaced = _IMG_SRC_PATTERN.sub(_sub_src, html)
    replaced = _EMPTY_IMG_PATTERN.sub("", replaced)
    return replaced
