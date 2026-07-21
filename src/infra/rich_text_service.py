"""RichTextService - 富文本服务（Infrastructure）

处理 MinIO 签名、占位符迁移和删除。
"""
import logging
import re
from typing import Optional

from src.infra.storage import Storage
from src.infra.rich_text import RichText

logger = logging.getLogger(__name__)

# 占位符正则: 匹配 editor://temp/{filename}
_TEMP_PLACEHOLDER_PATTERN = re.compile(
    r"""(<img\b[^>]*?\bsrc=["'])editor://temp/([^"'\s>]+)(["'][^>]*?/?>)""",
    flags=re.IGNORECASE,
)


class RichTextService:
    """富文本服务 - 处理 MinIO 签名、占位符迁移和删除"""

    def __init__(self, storage: Storage):
        self._storage = storage

    # ---- 上传签名 ----

    def get_upload_url(
        self,
        content_type: str,
    ) -> dict:
        """获取富文本图片上传预签名 URL。

        上传后 MinIO 路径: editor/temp/{uuid}.{ext}
        占位符: editor://temp/{uuid}.{ext}
        """
        import uuid
        file_id = uuid.uuid4().hex[:12]
        ext = ""
        stored_filename = file_id
        object_name = f"editor/temp/{stored_filename}"

        result = self._storage.get_presigned_upload_url(
            key=object_name,
            content_type=content_type,
            expiry=3600,
        )
        result["object_name"] = object_name
        result["placeholder"] = f"editor://temp/{stored_filename}"
        result["filename"] = stored_filename
        return result

    # ---- 下载签名 ----

    def sign_html(
        self,
        html: Optional[str],
        entity_type: str,
        entity_id: int,
        expiry: int = 3600,
    ) -> Optional[str]:
        """渲染时：将 HTML 中的占位符替换为预签名 URL。

        占位符格式：
        - editor://temp/{filename} -> 签名 editor/temp/{filename}
        - editor://{entity}/{id}/{filename} -> 签名 editor/{entity}/{id}/{filename}
        """
        if not html:
            return html

        paths = RichText.extract_filenames(html)
        if not paths:
            return html

        url_map = {}
        for path in paths:
            object_name = f"editor/{path}"
            url_map[path] = self._storage.get_presigned_download_url(
                key=object_name,
                original_name=None,
                expiry=expiry,
                as_attachment=False,
            )

        return RichText.replace_in_html(html, url_map)

    # ---- 保存时迁移：temp -> final ----

    def process_html(
        self,
        html: Optional[str],
        entity_type: str,
        entity_id: int,
    ) -> Optional[str]:
        """保存时：将 HTML 中的 temp 占位符迁移到最终路径。

        流程：
        1. 提取所有 editor://temp/* 占位符
        2. MinIO 复制: editor/temp/{file} -> editor/{entity}/{id}/{file}
        3. 删除 editor/temp/{file}
        4. 替换占位符: editor://temp/{file} -> editor://{entity}/{id}/{file}

        返回处理后的 HTML。
        """
        if not html:
            return html

        paths = list(set(
            match.group(2) for match in _TEMP_PLACEHOLDER_PATTERN.finditer(html)
        ))
        if not paths:
            return html

        for temp_path in paths:
            src_key = f"editor/temp/{temp_path}"
            dst_key = f"editor/{entity_type}/{entity_id}/{temp_path}"

            # 复制到最终路径
            ok = self._storage.copy_object(src_key, dst_key)
            if not ok:
                logger.warning(
                    "RichTextService.process_html: 复制文件失败 src=%s dst=%s",
                    src_key, dst_key,
                )
                continue

            # 删除临时文件
            self._storage.delete(src_key)

            # 替换 HTML 中的占位符
            html = html.replace(f"editor://temp/{temp_path}", f"editor://{entity_type}/{entity_id}/{temp_path}")

        return html

    # ---- 删除 ----

    def delete_by_entity(self, entity_type: str, entity_id: int) -> int:
        """删除 entity 的所有富文本文件。"""
        prefix = RichText.get_storage_prefix(entity_type, entity_id)
        return self._storage.delete_prefix(prefix)
