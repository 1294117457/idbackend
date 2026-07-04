"""本地文件系统实现（开发 / 单测用，不依赖 MinIO）

把 key 当作相对路径写到 base_dir 下；
get_access_url 返回 /static/{key}，需要 Nginx 代理 static_dir 到 base_dir。
"""
import os
from typing import BinaryIO

from src.infra.storage.base import Storage


class LocalAdapter(Storage):
    """本地文件系统 Adapter（仅用于本地开发 / 单元测试）"""

    def __init__(self, base_dir: str):
        self._base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)

    def _safe_join(self, key: str) -> str:
        """防止路径穿越：剔除 '..' 和绝对路径前缀"""
        key = key.replace("..", "").lstrip("/\\")
        return os.path.join(self._base_dir, key)

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

    def get_access_url(self, key: str, expiry: int = 3600) -> str:
        # 本地存储走 Nginx 静态目录（dev 环境假设有 Nginx /static/ 代理）
        return f"/static/{key}"

    def get_public_url(self, key: str) -> str:
        # 本地存储：公开读 = 同一静态 URL（无签名）
        return f"/static/{key}"

    def ensure_bucket(self) -> None:
        os.makedirs(self._base_dir, exist_ok=True)

    def close(self) -> None:
        # 本地文件无需关闭资源
        pass
