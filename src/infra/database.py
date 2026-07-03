"""PostgreSQL 数据库连接"""
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from typing import Generator
import logging

from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# 将 postgresql:// 转换为 postgresql+asyncpg://
def _make_async_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url

# 异步引擎 (主要使用)
async_engine = create_async_engine(
    _make_async_url(settings.DATABASE_URL),
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
    settings.DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://"),
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


async def init_db():
    """初始化数据库 (创建表等)"""
    from models.base import Base
    from models import user, application, template, file, config

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("数据库初始化完成")


async def close_db():
    """关闭数据库连接"""
    await async_engine.dispose()
