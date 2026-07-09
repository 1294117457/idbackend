"""MinIO（AWS S3 兼容对象存储）的 Adapter 实现

继承 Storage(ABC)；只 import botocore/boto3，不向外暴露任何 boto3 类型。
配置项从 settings 读，构造时一次确定，后续不可变（boto3 client 限制）。

迁移说明：
- 原 S3Adapter 适配 SeaweedFS（S3 兼容网关）；
- 现统一改名为 MinIOAdapter，后端从 SeaweedFS 切到 MinIO。
- boto3 端不感知，MinIO 实现 100% 兼容 AWS S3 API。
"""
from typing import BinaryIO
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from src.infra.config import get_settings
from src.infra.storage.base import Storage


class MinIOAdapter(Storage):
    """MinIO / AWS S3 兼容对象存储实现

    通过 boto3 客户端访问 MinIO（兼容 AWS S3 v4 签名协议）。
    """

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        max_pool_connections: int = 50,
        connect_timeout: int = 5,
        read_timeout: int = 30,
        max_retries: int = 3,
    ):
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="us-east-1",
            config=Config(
                signature_version="s3v4",
                max_pool_connections=max_pool_connections,
                connect_timeout=connect_timeout,
                read_timeout=read_timeout,
                retries={"max_attempts": max_retries, "mode": "standard"},
                tcp_keepalive=True,
            ),
        )
        # 直链前缀（公开桶 / Nginx 代理使用）
        self._public_url = endpoint.rstrip("/")
        self._max_pool_connections = max_pool_connections

    # ============= 业务操作 =============

    async def upload(
        self,
        file_obj: BinaryIO,
        key: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=file_obj.read(),
            ContentType=content_type,
        )
        return key

    async def download(self, key: str) -> bytes:
        resp = self._client.get_object(Bucket=self._bucket, Key=key)
        return resp["Body"].read()

    async def delete(self, key: str) -> bool:
        self._client.delete_object(Bucket=self._bucket, Key=key)
        return True

    def get_access_url(self, key: str, expiry: int = 3600) -> str:
        # boto3 签名：ClientMethod 是必填位置参数；选 'get_object' 是为了让预签 URL
        # 可以真正 GET 到对象。Params 内的 Bucket/Key 是签名的资源标识。
        return self._client.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expiry,
        )

    def get_public_url(self, key: str) -> str:
        return f"{self._public_url}/{self._bucket}/{key}"

    def set_bucket_public_read_prefix(self, prefix: str) -> None:
        """对 bucket 下指定前缀应用 anonymous=download 策略

        AWS S3 / MinIO 都用 put_bucket_policy；前缀即 object key 的前缀，
        例如 "avatar/" 表示只放开 avatar/ 下的对象 GET，其他 key 仍受 ACL 控制。
        """
        import json
        from botocore.exceptions import ClientError

        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": f"AllowPublicRead{prefix.strip('/').replace('/', '-').replace('*', 'all') or 'all'}",
                    "Effect": "Allow",
                    "Principal": {"AWS": ["*"]},
                    "Action": ["s3:GetObject"],
                    "Resource": [
                        f"arn:aws:s3:::{self._bucket}/{prefix.strip('/')}/*"
                    ],
                }
            ],
        }
        # prefix 若为空则允许整个 bucket 公开读
        policy["Statement"][0]["Resource"] = (
            [f"arn:aws:s3:::{self._bucket}/*"]
            if not prefix.strip()
            else policy["Statement"][0]["Resource"]
        )
        try:
            self._client.put_bucket_policy(
                Bucket=self._bucket,
                Policy=json.dumps(policy),
            )
            print(f"[MinIOAdapter] 已对 {self._bucket}/{prefix} 设置公开读策略")
        except ClientError as e:
            print(f"[MinIOAdapter] 设置公开读策略失败: {e}")
            raise

    # ============= 生命周期 =============

    def ensure_bucket(self) -> None:
        """确保目标 bucket 存在

        MinIO 兼容 head_bucket / create_bucket 协议；
        如果 bucket 不存在则创建，LocationConstraint 在 MinIO 上忽略。
        """
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self._bucket)

    def close(self) -> None:
        """释放 boto3 client"""
        self._client.close()


def build_default_minio_adapter() -> MinIOAdapter:
    s = get_settings()
    return MinIOAdapter(
        endpoint=s.MINIO_ENDPOINT,
        access_key=s.MINIO_ACCESS_KEY,
        secret_key=s.MINIO_SECRET_KEY,
        bucket=s.MINIO_BUCKET,
        max_pool_connections=s.MINIO_MAX_POOL_CONNECTIONS,
        connect_timeout=s.MINIO_CONNECT_TIMEOUT,
        read_timeout=s.MINIO_READ_TIMEOUT,
        max_retries=s.MINIO_MAX_RETRIES,
    )
