"""RichTextService - 富文本服务（Infrastructure）

处理 MinIO 签名、占位符迁移和删除。
"""
import logging
import re
from typing import Optional

from src.infra.storage import Storage
from src.infra.rich_text import RichText

logger = logging.getLogger(__name__)


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

        返回格式: /editor/{path}?签名参数
        供 Vite 代理到 MinIO。

        占位符格式：
        - editor://temp/{filename} -> 签名 /editor/temp/{filename}?签名
        - editor://{entity}/{id}/{filename} -> 签名 /editor/{entity}/{id}/{filename}?签名
        """
        if not html:
            return html

        paths = RichText.extract_filenames(html)
        if not paths:
            return html

        bucket = self._storage._bucket
        url_map = {}
        for path in paths:
            object_name = f"editor/{path}"
            # 获取带签名的相对路径：/{bucket}/editor/{path}?sig...
            signed_path = self._storage.get_presigned_download_url(
                key=object_name,
                original_name=None,
                expiry=expiry,
                as_attachment=False,
            )
            # 去掉 /{bucket} 前缀，只保留 /editor/{path}?sig 格式
            # MinIO 返回格式: /{bucket}/editor/{path}?sig
            # bucket_prefix = f"/{bucket}/"
            # if signed_path.startswith(bucket_prefix):
                # signed_path = signed_path[len(bucket_prefix):]  # 去掉 /{bucket}/
            # 确保以 /editor/ 开头
            # if not signed_path.startswith("/editor/"):
            #     signed_path = "/" + signed_path
            url_map[path] = signed_path

        return RichText.replace_in_html(html, url_map)

    # ---- 保存时：签名 URL -> 占位符 ----

    def process_html(
        self,
        html: Optional[str],
        entity_type: str,
        entity_id: int,
    ) -> Optional[str]:
        """保存时：将 HTML 中的签名 URL 替换为占位符。

        同时处理两种 URL 格式（兼容不同时期的签名输出）：
        - /{bucket}/editor/{path}?签名  （MinIO 标准格式）
        - /editor/{path}?签名          （旧版格式）
        对于 editor/temp/ 开头的文件，同时迁移到最终路径。

        查询参数中的 & 在 HTML 属性里可能被编码为 &amp;，
        正则用 (?:&amp;|&) 兼容两种写法，避免全局替换破坏正文。

        输出格式: <img src="editor://{path}" ...>
        """
        if not html:
            return html

        bucket = re.escape(self._storage._bucket)

        # 查询参数部分：允许 & 或 &amp; 作为分隔符
        _QS = r"""(?:\?(?:[^"'\s]|&amp;)*)?"""

        # 匹配两种格式：/{bucket}/editor/... 或 /editor/...
        pattern = re.compile(
            rf'(src=["\'])(?:/{bucket})?/editor/([^"\'?\s&]+){_QS}(["\'])',
            flags=re.IGNORECASE,
        )

        seen: set[str] = set()
        replacements: list[tuple[str, str]] = []

        for match in pattern.finditer(html):
            path = match.group(2)
            if path in seen:
                continue
            seen.add(path)

            if path.startswith("temp/"):
                filename = path[5:]
                src_key = f"editor/{path}"
                dst_key = f"editor/{entity_type}/{entity_id}/{filename}"

                ok = self._storage.copy_object(src_key, dst_key)
                if not ok:
                    logger.warning(
                        "RichTextService.process_html: 复制文件失败 src=%s dst=%s",
                        src_key, dst_key,
                    )
                else:
                    self._storage.delete(src_key)

                dst_placeholder = f"editor://{entity_type}/{entity_id}/{filename}"
            else:
                dst_placeholder = f"editor://{path}"

            replacements.append((path, dst_placeholder))

        for path, dst_placeholder in replacements:
            replace_pattern = re.compile(
                rf'(src=["\'])(?:/{bucket})?/editor/{re.escape(path)}{_QS}(["\'])',
                flags=re.IGNORECASE,
            )
            html = replace_pattern.sub(rf'\1{dst_placeholder}\2', html)

        return html

    # ---- 删除 ----

    def delete_by_entity(self, entity_type: str, entity_id: int) -> int:
        """删除 entity 的所有富文本文件。"""
        prefix = RichText.get_storage_prefix(entity_type, entity_id)
        return self._storage.delete_prefix(prefix)
