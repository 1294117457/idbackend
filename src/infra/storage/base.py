"""存储抽象基类 —— 所有存储后端必须实现的契约

业务只依赖这个接口，不依赖任何具体实现（boto3 / 本地文件 / ...）。
通过 Depends(get_storage) 注入；类型注解是 Storage，运行时是 MinIOAdapter / LocalAdapter。
"""
from abc import ABC, abstractmethod
from typing import BinaryIO


class Storage(ABC):
    """文件存储的统一接口"""

    # ============= 业务操作 =============

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
    def get_access_url(self, key: str, expiry: int = 3600) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_public_url(self, key: str) -> str:
        raise NotImplementedError

    def set_bucket_public_read_prefix(self, prefix: str) -> None:
        """将 bucket 指定前缀设为公开读（匿名下载）。

        本地适配器无需实现，默认 no-op。
        对象存储适配器（MinIO / S3）应 override 以调用 put_bucket_policy。
        """
        return None

    # ============= 生命周期 =============

    @abstractmethod
    def ensure_bucket(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError
