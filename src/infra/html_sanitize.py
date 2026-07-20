"""富文本 HTML 净化（防 XSS）—— Template.description 专用

设计原则：
1. 白名单标签 + 白名单属性 + 白名单 URL scheme（默认拒绝 javascript:）
2. <a> 自动添加 rel="noopener noreferrer nofollow"
3. 限制最大长度（防巨 payload DoS）
4. sanitize 是幂等的：对纯文本等同 passthrough；对 HTML 是危险元素剥离
5. 仅用于 description 字段（业务要求富文本），其余字段仍按纯文本处理

修改历史：
- 2026-07-19: v1 初版
"""
from typing import Optional

import nh3


# 标签白名单（业务允许的语义元素）
_ALLOWED_TAGS = {
    # 块级
    "p", "br", "div", "blockquote", "pre",
    # 标题
    "h1", "h2", "h3", "h4", "h5", "h6",
    # 行内
    "strong", "em", "u", "s", "code", "span",
    # 列表
    "ul", "ol", "li",
    # 媒体
    "img", "a",
}

# 属性白名单：tag → 属性集；"*" 表示通用
# 注意：不包含 id/name（防锚点劫持）；style 仅 img 允许（其他标签不需要内联样式）
_ALLOWED_ATTRS = {
    "*": {"class"},  # 仅允许 class（用于对齐/字号控制）
    "a": {"href", "title"},
    # img：允许 style（用于"图片尺寸"功能）；width/max-width/height/height 等尺寸类
    # 需要配合 filter_style_properties 进一步过滤 CSS 属性（nh3 的 style 二级白名单机制）
    "img": {"src", "alt", "title", "style"},
}

# style 内部允许的 CSS 属性白名单（只放尺寸相关）
# 严格禁止 position/z-index/opacity/transform 等可能被滥用来攻击的属性
_ALLOWED_STYLE_PROPS = {
    "width",
    "height",
    "max-width",
    "max-height",
    "min-width",
    "min-height",
}

# URL 协议白名单（拒绝 javascript:、vbscript:、file: 等）
_URL_SCHEMES = {
    "http", "https", "mailto",
    "editor",  # 占位协议：editor://object/{key}（富文本图片引用，key 是 MinIO object_name，后端渲染时按 key 签预签名 URL）
}

# 富文本最大长度（防巨 payload DoS / 误传）
_MAX_LEN = 200_000  # 200KB


def sanitize_html(dirty: Optional[str]) -> Optional[str]:
    """净化 HTML 字符串

    :param dirty: 原始 HTML 字符串（可为 None）
    :return: 净化后的 HTML；空字符串归一化为 None
    :raises ValueError: 长度超过上限时抛错
    """
    if dirty is None:
        return None
    if not isinstance(dirty, str):
        raise ValueError("description 必须是字符串")

    # 长度校验（sanitize 之前的输入）
    if len(dirty) > _MAX_LEN:
        raise ValueError(
            f"description 长度 {len(dirty)} 超过上限 {_MAX_LEN}"
        )

    cleaned = nh3.clean(
        dirty,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        url_schemes=_URL_SCHEMES,
        # <a> 自动添加 rel 属性（防 tabnabbing / referrer 泄漏）
        link_rel="noopener noreferrer nofollow",
        # 允许 <img style="...">，但只保留尺寸相关 CSS 属性
        # （防 position:fixed / z-index / opacity / transform 等被用于 clickjacking / UI redress）
        filter_style_properties=_ALLOWED_STYLE_PROPS,
    )

    # 空字符串归一化为 None（节约存储）
    if not cleaned.strip():
        return None

    return cleaned
