"""PostgreSQL 数据库连接"""
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from typing import Generator
import logging

from .config import (
    get_settings,
    get_async_database_url,
    get_sync_database_url,
)

logger = logging.getLogger(__name__)
settings = get_settings()

# 异步引擎 (主要使用)
async_engine = create_async_engine(
    get_async_database_url(),
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# 同步引擎 (迁移和初始化使用)
sync_engine = create_engine(
    get_sync_database_url(),
    echo=settings.DEBUG,
    pool_pre_ping=True,
)

SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncSession:
    """获取数据库会话"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


@contextmanager
def get_sync_db() -> Generator[Session, None, None]:
    """获取同步数据库会话 (用于迁移等场景)"""
    with SyncSessionLocal() as session:
        try:
            yield session
        finally:
            session.close()


async def close_db():
    """关闭数据库连接"""
    await async_engine.dispose()
