from datetime import datetime, timezone, timedelta
from typing import BinaryIO, Optional
from urllib.parse import quote, urlparse, parse_qs, urlencode

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from src.infra.config import get_settings
from src.infra.storage.base import Storage


class MinIOAdapter(Storage):
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
        self._public_url = endpoint.rstrip("/")

    # ============ 基础操作 ============

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

    def delete_prefix(self, prefix: str) -> int:
        """删除指定前缀下的所有对象，返回删除数量。"""
        prefix = prefix.strip("/")
        count = 0

        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=f"{prefix}/"):
            objects = page.get("Contents", [])
            if not objects:
                continue
            keys = [{"Key": obj["Key"]} for obj in objects]
            self._client.delete_objects(
                Bucket=self._bucket,
                Delete={"Objects": keys},
            )
            count += len(keys)

        return count

    def copy_object(self, src_key: str, dst_key: str) -> bool:
        """复制对象到新 key，返回是否成功。"""
        try:
            self._client.copy_object(
                Bucket=self._bucket,
                CopySource=f"{self._bucket}/{src_key}",
                Key=dst_key,
            )
            return True
        except ClientError:
            return False

    # ============ 公开访问 ============

    def get_public_url(self, key: str) -> str:
        return f"{self._public_url}/{self._bucket}/{key}"



    # ============ 私有访问 ============

    def get_presigned_upload_url(
        self,
        key: str,
        content_type: str = "application/octet-stream",
        expiry: int = 3600,
    ) -> dict:
        url = self._client.generate_presigned_url(
            ClientMethod="put_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expiry,
        )
        return {
            "url": url,
            "headers": {"Content-Type": content_type},
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(seconds=expiry)
            ).isoformat().replace("+00:00", "Z"),
        }

    def get_presigned_download_url(
        self,
        key: str,
        original_name: Optional[str] = None,
        expiry: int = 3600,
        as_attachment: bool = True,
    ) -> str:
        params = {"Bucket": self._bucket, "Key": key}
        if as_attachment:
            if original_name:
                encoded = quote(original_name, safe="")
                params["ResponseContentDisposition"] = (
                    f"attachment; filename*=UTF-8''{encoded}"
                )
            else:
                params["ResponseContentDisposition"] = "attachment"
        full_url = self._client.generate_presigned_url(
            ClientMethod="get_object",
            Params=params,
            ExpiresIn=expiry,
        )
        # 返回相对路径：/bucket/key?query_string
        parsed = urlparse(full_url)
        query_params = parse_qs(parsed.query)
        query_string = urlencode(query_params, safe="")
        relative_path = f"/{self._bucket}/{key}"
        if query_string:
            relative_path = f"{relative_path}?{query_string}"
        return relative_path

    # ============ 生命周期 ============

    def ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self._bucket)

        try:
            self._client.delete_bucket_policy(Bucket=self._bucket)
        except ClientError:
            pass


    def set_public_read_prefix(self, prefix: str) -> None:
        import json

        clean_prefix = prefix.strip("/")
        sid_suffix = clean_prefix.replace("/", "-") or "all"

        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": f"PublicRead{sid_suffix}",
                    "Effect": "Allow",
                    "Principal": {"AWS": ["*"]},
                    "Action": ["s3:GetObject"],
                    "Resource": f"arn:aws:s3:::{self._bucket}/{clean_prefix}/*",
                }
            ],
        }
        self._client.put_bucket_policy(
            Bucket=self._bucket,
            Policy=json.dumps(policy),
        )

    def close(self) -> None:
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
