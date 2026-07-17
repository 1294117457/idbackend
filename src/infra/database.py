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
# 关键参数：
# - pool_size/max_overflow: 控制单 worker 向 PG 申请的最大连接数
# - pool_timeout: 等不到连接多久超时（5s 防止雪崩）
# - pool_recycle: 连接 1800s 后回收，防止 stale connection
# - pool_pre_ping: 取出连接时 ping 一次 PG，确保连接有效
# - connect_args: 给 asyncpg 设置 5s 连接超时和 command 超时
async_engine = create_async_engine(
    get_async_database_url(),
    echo=False,
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_recycle=1800,
    connect_args={
        "timeout": 5,                 # asyncpg 连接超时 5s
        "command_timeout": 10,        # 单个 SQL 命令超时 10s（慢查询直接杀）
    },
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
    """获取数据库会话（async with 自动 close，无需手动 await close）"""
    async with AsyncSessionLocal() as session:
        yield session


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
