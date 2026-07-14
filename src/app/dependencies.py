"""FastAPI 依赖注入层

只做"依赖对象的构造"，不做业务校验、不做 HTTP 逻辑。
- _storage         → Storage 模块级单例（由 main.py lifespan 初始化/关闭）
- get_storage      → 返回单例
- get_file_service → FileService（注入 db + storage）
"""
from functools import lru_cache

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.infra.database import get_db
from src.infra.storage import Storage
from src.services.file_service import FileService

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


def get_file_service(
    db: AsyncSession = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> FileService:
    return FileService(db=db, storage=storage)


__all__ = ["get_storage", "set_storage", "clear_storage", "get_file_service"]