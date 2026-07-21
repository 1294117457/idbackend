"""本地文件系统实现（开发 / 单测用，不依赖 MinIO）

把 key 当作相对路径写到 base_dir 下；
get_public_url 返回 /static/{key}，需要 Nginx 代理 static_dir 到 base_dir。
"""
import os
from typing import BinaryIO, Optional

from src.infra.storage.base import Storage


class LocalAdapter(Storage):
    """本地文件系统 Adapter（仅用于本地开发 / 单元测试）"""

    def __init__(self, base_dir: str):
        self._base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)

    def _safe_join(self, key: str) -> str:
        key = key.replace("..", "").lstrip("/\\")
        return os.path.join(self._base_dir, key)

    # ============ 基础操作 ============

    async def upload(
        self,
        file_obj: BinaryIO,
        key: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        path = self._safe_join(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(file_obj.read())
        return key

    async def download(self, key: str) -> bytes:
        path = self._safe_join(key)
        with open(path, "rb") as f:
            return f.read()

    async def delete(self, key: str) -> bool:
        path = self._safe_join(key)
        if os.path.exists(path):
            os.remove(path)
        return True

    def delete_prefix(self, prefix: str) -> int:
        """删除指定前缀下的所有文件"""
        prefix = prefix.strip("/")
        full_prefix = os.path.join(self._base_dir, prefix)
        count = 0

        if not os.path.exists(full_prefix):
            return 0

        for root, dirs, files in os.walk(full_prefix, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
                count += 1
            os.rmdir(root)

        return count

    # ============ 公开访问 ============

    def get_public_url(self, key: str) -> str:
        return f"/static/{key}"

    def set_public_read_prefix(self, prefix: str) -> None:
        pass  # 本地存储无权限概念

    # ============ 私有访问 ============

    def get_presigned_upload_url(
        self,
        key: str,
        content_type: str = "application/octet-stream",
        expiry: int = 3600,
    ) -> dict:
        raise NotImplementedError(
            "LocalAdapter 不支持签名上传；开发环境请直接走 POST /api/file/upload 中转流"
        )

    def get_presigned_download_url(
        self,
        key: str,
        original_name: Optional[str] = None,
        expiry: int = 3600,
        as_attachment: bool = True,
    ) -> str:
        """本地存储直接返回静态路径，无签名"""
        return f"/static/{key}"

    # ============ 生命周期 ============

    def ensure_bucket(self) -> None:
        os.makedirs(self._base_dir, exist_ok=True)

    def close(self) -> None:
        pass
