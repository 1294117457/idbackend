"""环境配置"""
from pathlib import Path
from functools import lru_cache
from pydantic_settings import BaseSettings


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

    # SeaweedFS (S3兼容)
    S3_ENDPOINT: str = "http://localhost:8333"
    S3_ACCESS_KEY: str = "admin"
    S3_SECRET_KEY: str = "password"
    S3_BUCKET: str = "idproject"

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

    class Config:
        env_file = str(_ENV_FILE)
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
