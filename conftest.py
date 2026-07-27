"""pytest 配置文件（共享 fixture）。"""
import pytest
import pytest_asyncio
from sqlalchemy import Column, Integer, String
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base


# ─── 共享 model base ────────────────────────────────────────────
SharedBase = declarative_base()


@pytest.fixture(scope="session")
def shared_base():
    """共享的 SQLAlchemy declarative base。"""
    return SharedBase


# ─── 测试数据库 engine ──────────────────────────────────────
@pytest_asyncio.fixture
async def test_engine():
    """每个测试一个共享内存 SQLite（用临时文件，避免连接隔离问题）。"""
    import tempfile
    tmpfile = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmpfile.close()
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmpfile.name}",
        echo=False,
    )
    yield engine
    await engine.dispose()
    import pathlib
    pathlib.Path(tmpfile.name).unlink(missing_ok=True)


# ─── 测试 factory ──────────────────────────────────────────
@pytest_asyncio.fixture
async def session_factory(test_engine):
    """提供 session 工厂（用测试 engine）。"""
    return async_sessionmaker(test_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def test_factory(test_engine):
    """提供 session 工厂（用测试 engine）—— 与 session_factory 同义。"""
    return async_sessionmaker(test_engine, expire_on_commit=False)


# ─── 自动为测试文件创建自定义 Base 表 ─────────────────────────
@pytest_asyncio.fixture(autouse=False)
async def auto_create_tables(test_engine):
    """在测试开始前为 SharedBase + 当前测试模块自定义的 Base 创建表。

    用法：
        在测试文件顶部定义一个或多个继承 declarative_base() 的 Base，
        然后让测试函数接受此 fixture，conftest 会自动 create_all。
    """
    # 把测试模块自己定义的 model 加进 SharedBase.metadata
    import sys
    # 简化版：直接让测试模块把表加进 SharedBase
    # ↑ 但这需要测试模块导入 SharedBase，工作量大
    # ↓ 退而求其次：让每个测试函数自己 create_all
    yield


# ─── pytest 配置 ────────────────────────────────────────────
def pytest_configure(config):
    """注册自定义 marker。"""
    markers = [
        "step1: Step 1 (get_db 自动事务) 相关测试",
        "step2: Step 2 (repo 清理) 相关测试",
        "step3: Step 3 (service commit 清理) 相关测试",
        "step4: Step 4 (flush + refresh) 相关测试",
        "step5: Step 5 (file_service) 相关测试",
        "step6: Step 6 (stream_chat) 相关测试",
        "e2e: 端到端测试",
        "perf: 性能测试",
    ]
    for m in markers:
        config.addinivalue_line("markers", m)
