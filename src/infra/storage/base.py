"""存储抽象基类 —— 所有存储后端必须实现的契约"""
from abc import ABC, abstractmethod
from typing import BinaryIO, Optional


class Storage(ABC):
    """文件存储的统一接口"""

    # ============ 基础操作 ============

    @abstractmethod
    async def upload(
        self,
        file_obj: BinaryIO,
        key: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        raise NotImplementedError

    @abstractmethod
    async def download(self, key: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, key: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def delete_prefix(self, prefix: str) -> int:
        """删除指定前缀下的所有对象，返回删除数量。"""
        raise NotImplementedError

    @abstractmethod
    def copy_object(self, src_key: str, dst_key: str) -> bool:
        """复制对象，返回是否成功。"""
        raise NotImplementedError

    # ============ 公开访问（头像）============

    @abstractmethod
    def get_public_url(self, key: str) -> str:
        raise NotImplementedError

    def set_public_read_prefix(self, prefix: str) -> None:
        """将指定前缀设为公开读（匿名下载）。

        本地适配器默认 no-op；MinIO/S3 适配器 override 调用 put_bucket_policy。
        """

    # ============ 私有访问（预签名）============

    @abstractmethod
    def get_presigned_upload_url(
        self,
        key: str,
        content_type: str = "application/octet-stream",
        expiry: int = 3600,
    ) -> dict:
        """返回预签名上传 URL + headers。

        返回格式：
        {
            "url": "https://...",
            "headers": {"Content-Type": "image/jpeg"},
            "expires_at": "2025-01-01T00:00:00Z"
        }
        """
        raise NotImplementedError

    @abstractmethod
    def get_presigned_download_url(
        self,
        key: str,
        original_name: Optional[str] = None,
        expiry: int = 3600,
        as_attachment: bool = True,
    ) -> str:
        raise NotImplementedError

    # ============ 生命周期 ============

    @abstractmethod
    def ensure_bucket(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError
