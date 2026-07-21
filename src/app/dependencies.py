"""FastAPI 依赖注入层

只做"依赖对象的构造"，不做业务校验、不做 HTTP 逻辑。

依赖项:
- get_db              → 数据库会话（from src.infra.database）
- ip_rate_limit      → IP 维度限流工厂
- _storage            → Storage 模块级单例（由 main.py lifespan 初始化/关闭）
- get_storage         → 返回单例
- get_file_service    → FileService（注入 db + storage）

认证/鉴权由中间件完成，用户信息通过 src.app.context 直接读取。
"""
from functools import lru_cache

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.infra.database import get_db
from src.infra.storage import Storage
from src.infra.redis import get_redis, RedisCache
from src.services.file_service import FileService
from src.infra.rich_text_service import RichTextService


# ════════════════════════════════════════════════════════════════
# Storage 生命周期管理
# ════════════════════════════════════════════════════════════════

_storage: Storage | None = None


def set_storage(storage: Storage) -> None:
    global _storage
    _storage = storage


def get_storage() -> Storage:
    if _storage is None:
        raise RuntimeError("Storage not initialized. Ensure lifespan started.")
    return _storage


def clear_storage() -> None:
    global _storage
    _storage = None


# ════════════════════════════════════════════════════════════════
# Service 依赖注入
# ════════════════════════════════════════════════════════════════

def get_file_service(
    db: AsyncSession = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> FileService:
    return FileService(db=db, storage=storage)


def get_rich_text_service(
    storage: Storage = Depends(get_storage),
) -> RichTextService:
    return RichTextService(storage=storage)


# ════════════════════════════════════════════════════════════════
# 限流
# ════════════════════════════════════════════════════════════════

def ip_rate_limit(action: str, max_count: int, window_seconds: int):
    """IP 维度限流 Depends 工厂，超限时直接抛 429"""
    async def _check(request: Request):
        client_ip = request.client.host if request.client else "unknown"
        cache = RedisCache(await get_redis())
        allowed, _ = await cache.rate_limit(
            f"rl:ip:{action}:{client_ip}", max_count=max_count, window_seconds=window_seconds
        )
        if not allowed:
            raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")
    return _check


__all__ = [
    "get_db",
    "get_storage",
    "set_storage",
    "clear_storage",
    "get_file_service",
    "get_rich_text_service",
    "ip_rate_limit",
]
