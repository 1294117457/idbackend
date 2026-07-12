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
    SYSTEM_ACCOUNTS: str = "admin"
    ALLOWED_ORIGINS: List[str] = ["*"]

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


# ────── 数据库 URL 转换（统一实现，唯一一处） ──────
def to_async_database_url(url: str) -> str:
    """postgresql:// → postgresql+asyncpg://

    若已是 +asyncpg 或 +psycopg2 则原样返回（幂等）。
    """
    if (
        url.startswith("postgresql://")
        and "+asyncpg" not in url
        and "+psycopg2" not in url
    ):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def to_sync_database_url(url: str) -> str:
    """postgresql[+asyncpg]:// → postgresql+psycopg2://

    若已是 +psycopg2 则原样返回（幂等）。
    """
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://") and "+psycopg2" not in url:
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def get_async_database_url() -> str:
    """应用运行时用的 DB URL（asyncpg）"""
    return to_async_database_url(get_settings().DATABASE_URL)


def get_sync_database_url() -> str:
    """同步脚本（`Base.metadata.create_all` / `init_rbac_data` 等）用的 DB URL（psycopg2）"""
    return to_sync_database_url(get_settings().DATABASE_URL)


def is_system_account(username: str) -> bool:
    """判断用户名是否在超管白名单中（白名单用户拥有全部权限）"""
    accounts = get_settings().SYSTEM_ACCOUNTS
    return username in {acc.strip() for acc in accounts.split(",") if acc.strip()}
