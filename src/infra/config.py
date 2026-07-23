"""环境配置

分层策略：
  1. 静态配置（DB/Redis/Minio/JWT 等）→ 仅从 .env 读取
  2. 运行时配置（LLM/Embed/SMTP/RAG）→ DB 优先，.env 兜底

缓存刷新：
  - 启动时 lifespan 一次性填充
  - PUT /api/system/config/* 后调用 await refresh_cache() 立即刷新

使用方式：
  from src.infra.config import get_settings           # 静态配置
  from src.infra.config import get_llm_config         # LLM 配置
  from src.infra.config import get_embed_config       # Embedding 配置
  from src.infra.config import get_smtp_config        # SMTP 配置
  from src.infra.config import get_rag_config         # RAG 参数
  from src.infra.config import refresh_cache          # 手动刷新缓存（async）
"""

import threading
from pathlib import Path
from typing import Any, Dict, List

from pydantic_settings import BaseSettings, SettingsConfigDict


_ENV_FILE = Path(__file__).parent.parent.parent / ".env"


# ════════════════════════════════════════════════════════════════
# Layer 1: 静态配置（仅 .env，永不热更）
# ════════════════════════════════════════════════════════════════

class Settings(BaseSettings):
    # ── 服务 ────────────────────────────────────────────────────
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    DEBUG: bool = False

    # ── PostgreSQL ──────────────────────────────────────────────
    DATABASE_URL: str = "postgresql://postgres:password@localhost:5432/idproject"
    PG_VECTOR_URL: str = "postgresql://postgres:password@localhost:5432/idproject"

    # DB 连接池
    DB_POOL_SIZE: int = 30
    DB_MAX_OVERFLOW: int = 50
    DB_POOL_TIMEOUT: int = 30

    # ── Redis ───────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── MinIO（S3 兼容对象存储）─────────────────────────────────
    MINIO_ENDPOINT: str = "http://localhost:9000"
    MINIO_ACCESS_KEY: str = "admin"
    MINIO_SECRET_KEY: str = "password"
    MINIO_BUCKET: str = "idproject"
    MINIO_MAX_POOL_CONNECTIONS: int = 50
    MINIO_CONNECT_TIMEOUT: int = 5
    MINIO_READ_TIMEOUT: int = 30
    MINIO_MAX_RETRIES: int = 3

    storage_backend: str = "minio"
    local_storage_dir: str = "./storage"

    # ── JWT ─────────────────────────────────────────────────────
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 24
    JWT_REFRESH_EXPIRE_DAYS: int = 7

    # ── LLM / Chat 模型（.env 默认值）────────────────────────────
    LLM_PROVIDER: str = "openai"
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_CHAT_MODEL: str = "gpt-4o"

    # ── Embedding / 向量模型（.env 默认值）──────────────────────
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_BASE_URL: str = "https://api.openai.com/v1"
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIM: int = 1536

    # ── RAG 参数（.env 默认值，DB 优先覆盖）────────────────────
    # 字段名与 system_config DB 表保持一致
    RAG_TOP_K: int = 6          # 最终返回条数
    RAG_CANDIDATE_K: int = 0   # 候选池（0 = 自动公式 max(top_k*6, top_k+15)）
    RAG_RRF_K: int = 30
    RAG_SOURCE_DISCOUNT: float = 0.6
    RAG_BM25_RANK1_WEIGHT: float = 2.0
    # 切块参数（text_splitter 使用）
    RAG_CHUNK_SIZE: int = 400
    RAG_CHUNK_OVERLAP: int = 100

    # ── 上下文 ──────────────────────────────────────────────────
    CONTEXT_MAX_MESSAGES: int = 20

    # ── SMTP（.env 默认值）───────────────────────────────────────
    SMTP_HOST: str = "smtp.xmu.edu.cn"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""

    # ── 文件上传 ────────────────────────────────────────────────
    MAX_FILE_SIZE: int = 50 * 1024 * 1024
    MAX_PREVIEW_FILE_SIZE: int = 5 * 1024 * 1024
    SYSTEM_ACCOUNTS: str = "admin"
    ALLOWED_ORIGINS: List[str] = ["*"]

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )


_settings: Settings | None = None
_settings_lock = threading.Lock()


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        with _settings_lock:
            if _settings is None:
                _settings = Settings()
    return _settings


# ════════════════════════════════════════════════════════════════
# Layer 2: 运行时配置缓存（DB 优先，.env 兜底）
# ════════════════════════════════════════════════════════════════
#
# 缓存结构（与 SystemConfigService.get_all_config() 返回值一致）：
#   {
#     "llm":  {"provider": ..., "api_key": ..., ...},
#     "embed": {"api_key": ..., "base_url": ..., ...},
#     "smtp": {"host": ..., "port": ..., ...},
#     "rag":  {"search_mode": ..., "candidate_k": ..., ...},
#   }

_runtime_cache: Dict[str, Any] = {}
_cache_lock = threading.Lock()


async def refresh_cache(db) -> None:
    """从 DB 加载运行时配置并覆盖缓存（异步，lifespan / update 后调用）。"""
    from src.services.system_config_service import SystemConfigService

    data = await SystemConfigService.get_all_config(db)
    with _cache_lock:
        _runtime_cache.clear()
        _runtime_cache.update(data)


def _coalesce(db_cfg: Dict[str, Any], defaults: Dict[str, Any]) -> Dict[str, Any]:
    """DB 配置覆盖 .env 默认值，移除 None。"""
    result = dict(defaults)
    for k, v in db_cfg.items():
        if v is not None:
            result[k] = v
    return {k: v for k, v in result.items() if v is not None}


# ── LLM ───────────────────────────────────────────────────────────

def get_llm_config() -> Dict[str, Any]:
    defaults = {
        "provider": get_settings().LLM_PROVIDER,
        "api_key": get_settings().LLM_API_KEY,
        "base_url": get_settings().LLM_BASE_URL,
        "chat_model": get_settings().LLM_CHAT_MODEL,
    }
    return _coalesce(_runtime_cache.get("llm", {}), defaults)


# ── Embedding ─────────────────────────────────────────────────────

def get_embed_config() -> Dict[str, Any]:
    defaults = {
        "api_key": get_settings().EMBEDDING_API_KEY,
        "base_url": get_settings().EMBEDDING_BASE_URL,
        "model": get_settings().EMBEDDING_MODEL,
        "dim": get_settings().EMBEDDING_DIM,
    }
    return _coalesce(_runtime_cache.get("embed", {}), defaults)


# ── SMTP ──────────────────────────────────────────────────────────

def get_smtp_config() -> Dict[str, Any]:
    defaults = {
        "host": get_settings().SMTP_HOST,
        "port": get_settings().SMTP_PORT,
        "username": get_settings().SMTP_USERNAME,
        "password": get_settings().SMTP_PASSWORD,
        "from_addr": get_settings().SMTP_FROM,
    }
    return _coalesce(_runtime_cache.get("smtp", {}), defaults)


# ── RAG ───────────────────────────────────────────────────────────

def get_rag_config() -> Dict[str, Any]:
    """RAG 配置：DB 优先，.env 兜底，统一从 config.py 获取。

    字段名与 system_config DB 表保持完全一致。
    """
    defaults = {
        "top_k": get_settings().RAG_TOP_K,
        "candidate_k": get_settings().RAG_CANDIDATE_K,
        "rrf_k": get_settings().RAG_RRF_K,
        "source_discount": get_settings().RAG_SOURCE_DISCOUNT,
        "bm25_rank1_weight": get_settings().RAG_BM25_RANK1_WEIGHT,
        "chunk_size": get_settings().RAG_CHUNK_SIZE,
        "chunk_overlap": get_settings().RAG_CHUNK_OVERLAP,
    }
    return _coalesce(_runtime_cache.get("rag", {}), defaults)


# ════════════════════════════════════════════════════════════════
# Layer 3: 数据库 URL 转换（唯一实现）
# ════════════════════════════════════════════════════════════════

def to_async_database_url(url: str) -> str:
    """postgresql:// → postgresql+asyncpg://（幂等）"""
    if url.startswith("postgresql://") and "+asyncpg" not in url and "+psycopg2" not in url:
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def to_sync_database_url(url: str) -> str:
    """postgresql[+asyncpg]:// → postgresql+psycopg2://（幂等）"""
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://") and "+psycopg2" not in url:
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def get_async_database_url() -> str:
    return to_async_database_url(get_settings().DATABASE_URL)


def get_sync_database_url() -> str:
    return to_sync_database_url(get_settings().DATABASE_URL)


def is_system_account(username: str) -> bool:
    accounts = get_settings().SYSTEM_ACCOUNTS
    return username in {acc.strip() for acc in accounts.split(",") if acc.strip()}
