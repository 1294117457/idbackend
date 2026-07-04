"""环境配置"""

from pathlib import Path
from functools import lru_cache
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


_ENV_FILE = Path(__file__).parent.parent.parent / ".env"


class Settings(BaseSettings):
    # 服务配置
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    DEBUG: bool = False

    # PostgreSQL
    DATABASE_URL: str = "postgresql://postgres:password@localhost:5432/idproject"
    PG_VECTOR_URL: str = "postgresql://postgres:password@localhost:5432/idproject"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # MinIO（S3 兼容对象存储）
    # .env 字段名：MINIO_* （pydantic-settings 大小写不敏感，仍可用 S3_* 兼容老配置）
    MINIO_ENDPOINT: str = "http://localhost:9000"
    MINIO_ACCESS_KEY: str = "admin"
    MINIO_SECRET_KEY: str = "password"
    MINIO_BUCKET: str = "idproject"

    # MinIO 客户端调优（boto3 Config）
    MINIO_MAX_POOL_CONNECTIONS: int = 50         # 单 client 最大连接数；总并发 = workers × 该值
    MINIO_CONNECT_TIMEOUT: int = 5               # TCP 连接超时（秒）
    MINIO_READ_TIMEOUT: int = 30                 # 读超时（秒）
    MINIO_MAX_RETRIES: int = 3                   # 失败重试次数

    # 存储后端选择（minio / s3 / local）
    # 兼容别名：s3 等价于 minio（老 .env STORAGE_BACKEND=s3 仍生效）
    storage_backend: str = "minio"               # STORAGE_BACKEND=minio 或 =s3 或 =local
    local_storage_dir: str = "./storage"         # LocalAdapter 的根目录

    # JWT
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 24
    JWT_REFRESH_EXPIRE_DAYS: int = 7

    # LLM
    QWEN3_API_KEY: str = ""
    QWEN_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    QWEN_CHAT_MODEL: str = "qwen3-max"
    QWEN_EMBEDDING_MODEL: str = "text-embedding-v3"

    # 上下文
    CONTEXT_MAX_MESSAGES: int = 20

    # 邮件
    SMTP_HOST: str = "smtp.xmu.edu.cn"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""

    # 文件上传
    MAX_FILE_SIZE: int = 50 * 1024 * 1024  # 50MB

    # 系统超管白名单，逗号分隔，如 "zch,admin"
    # 对应 .env: SYSTEM_ACCOUNTS=zch,admin
    SYSTEM_ACCOUNTS: str = "admin"

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def is_system_account(username: str) -> bool:
    """判断用户名是否在超管白名单中（白名单用户拥有全部权限）"""
    accounts = get_settings().SYSTEM_ACCOUNTS
    return username in {acc.strip() for acc in accounts.split(",") if acc.strip()}
