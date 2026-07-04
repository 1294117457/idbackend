"""FastAPI 依赖注入层

只做"依赖对象的构造"，不做业务校验、不做 HTTP 逻辑。
- get_storage       → Storage 单例（lru_cache）
- get_file_service  → FileService（注入 db + storage）
"""
from functools import lru_cache

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.infra.database import get_db
from src.infra.storage import Storage, create_storage
from src.services.file_service import FileService


@lru_cache(maxsize=1)
def get_storage() -> Storage:
    return create_storage()


def get_file_service(
    db: AsyncSession = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> FileService:
    return FileService(db=db, storage=storage)


__all__ = ["get_storage", "get_file_service"]