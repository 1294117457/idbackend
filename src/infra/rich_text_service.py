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

        处理 /editor/{path}?签名 格式，将其替换为 editor://{path} 格式。
        对于 /editor/temp/ 开头的文件，同时迁移到最终路径。

        输出格式: <img src="editor://{path}" ...>
        """
        if not html:
            return html

        # 匹配所有 /editor/{path}?签名 格式
        pattern = re.compile(
            r'(src=["\'])/editor/([^"\'?\s&]+)(?:\?[^"\']*?)?(["\'])',
            flags=re.IGNORECASE,
        )

        # 去重处理
        seen: set[str] = set()
        replacements: list[tuple[str, str]] = []  # (src_pattern, dst_placeholder)

        for match in pattern.finditer(html):
            path = match.group(2)
            if path in seen:
                continue
            seen.add(path)

            if path.startswith("temp/"):
                # temp 文件：迁移到最终路径
                filename = path[5:]  # 去掉 "temp/"
                src_key = f"editor/{path}"
                dst_key = f"editor/{entity_type}/{entity_id}/{filename}"

                # 复制到最终路径
                ok = self._storage.copy_object(src_key, dst_key)
                if not ok:
                    logger.warning(
                        "RichTextService.process_html: 复制文件失败 src=%s dst=%s",
                        src_key, dst_key,
                    )
                    # 即使复制失败，也替换占位符（用最终路径的占位符）
                else:
                    # 删除临时文件
                    self._storage.delete(src_key)

                dst_placeholder = f"editor://{entity_type}/{entity_id}/{filename}"
            else:
                # 非 temp 文件：直接替换为占位符
                dst_placeholder = f"editor://{path}"

            replacements.append((path, dst_placeholder))

        # 执行替换
        for path, dst_placeholder in replacements:
            replace_pattern = re.compile(
                rf'(src=["\'])/editor/{re.escape(path)}(?:\?[^"\']*?)?(["\'])',
                flags=re.IGNORECASE,
            )
            html = replace_pattern.sub(rf'\1{dst_placeholder}\2', html)

        return html

    # ---- 删除 ----

    def delete_by_entity(self, entity_type: str, entity_id: int) -> int:
        """删除 entity 的所有富文本文件。"""
        prefix = RichText.get_storage_prefix(entity_type, entity_id)
        return self._storage.delete_prefix(prefix)
