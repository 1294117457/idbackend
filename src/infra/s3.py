"""SeaweedFS S3 客户端"""
from functools import lru_cache
from typing import Optional

from .config import get_settings

settings = get_settings()

_boto3 = None
_botocore = None


def _get_boto3():
    """延迟导入 boto3"""
    global _boto3
    if _boto3 is None:
        import boto3
        _boto3 = boto3
    return _boto3


def _get_botocore():
    """延迟导入 botocore"""
    global _botocore
    if _botocore is None:
        from botocore import config as botocore_config
        from botocore.exceptions import ClientError
        _botocore = (botocore_config, ClientError)
    return _botocore


class S3Client:
    """SeaweedFS S3 兼容客户端"""

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
    ):
        self.bucket = bucket
        boto3 = _get_boto3()
        botocore_config, ClientError = _get_botocore()

        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="us-east-1",
            config=botocore_config.Config(signature_version="s3v4"),
        )
        self._ClientError = ClientError

    def ensure_bucket(self):
        """确保 bucket 存在"""
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except self._ClientError:
            self.client.create_bucket(Bucket=self.bucket)

    def upload_file(
        self,
        file_data: bytes,
        object_name: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        """上传文件"""
        self.client.put_object(
            Bucket=self.bucket,
            Key=object_name,
            Body=file_data,
            ContentType=content_type,
        )
        return object_name

    def get_presigned_url(self, object_name: str, expiry: int = 3600) -> str:
        """生成预签名 URL"""
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": object_name},
            ExpiresIn=expiry,
        )

    def delete_file(self, object_name: str) -> bool:
        """删除文件"""
        self.client.delete_object(Bucket=self.bucket, Key=object_name)
        return True

    def download_file(self, object_name: str) -> bytes:
        """下载文件"""
        response = self.client.get_object(Bucket=self.bucket, Key=object_name)
        return response["Body"].read()


@lru_cache
def get_s3_client() -> S3Client:
    """获取 S3 客户端单例"""
    return S3Client(
        endpoint=settings.S3_ENDPOINT,
        access_key=settings.S3_ACCESS_KEY,
        secret_key=settings.S3_SECRET_KEY,
        bucket=settings.S3_BUCKET,
    )
