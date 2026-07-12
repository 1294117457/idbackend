"""存储抽象基类 —— 所有存储后端必须实现的契约

业务只依赖这个接口，不依赖任何具体实现（boto3 / 本地文件 / ...）。
通过 Depends(get_storage) 注入；类型注解是 Storage，运行时是 MinIOAdapter / LocalAdapter。
"""
from abc import ABC, abstractmethod
from typing import BinaryIO, Optional


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

    # ============= v6.0 新增：签名模式 =============

    @abstractmethod
    def get_presigned_upload_url(
        self,
        key: str,
        content_type: str = "application/octet-stream",
        content_length: Optional[int] = None,
        expiry: int = 3600,
    ) -> dict:
        """生成 MinIO 预签名 PUT URL（v6.0 预留接口，本期不启用）

        返回结构：
            {
                "url": "https://minio/...?X-Amz-Signature=xxx",
                "headers": {"Content-Type": "..."},
                "expires_at": "2026-07-12T19:00:00Z",
            }

        设计目的：未来支持浏览器直传，绕过应用服务器。
        本期（v6.0）改造不启用，签名上传留给 v7.0。
        LocalAdapter 应抛 NotImplementedError。
        """
        raise NotImplementedError

    @abstractmethod
    def get_download_url(
        self,
        key: str,
        original_name: Optional[str] = None,
        expiry: int = 3600,
        force_attachment: bool = True,
    ) -> str:
        """生成 MinIO 预签名 GET URL（v6.0 主用接口）

        Args:
            key: 对象键名
            original_name: 原始文件名（用于 Content-Disposition）
            expiry: URL 过期秒数（默认 3600 = 1 小时）
            force_attachment: True → 浏览器强制下载而非预览
                              （添加 response-content-disposition: attachment）

        Returns:
            预签名 URL（含 ResponseContentDisposition 参数）

        v6.0 行为：所有适配器都应实现。
        LocalAdapter 直接返回 /static/{key}。
        """
        raise NotImplementedError

    # ============= 生命周期 =============

    @abstractmethod
    def ensure_bucket(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError
