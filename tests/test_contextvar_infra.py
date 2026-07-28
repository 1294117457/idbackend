"""Step 1 测试：验证 ContextVar 基础设施。

依据：
    docs/docs-backend/dbcontext/step1-contextvar-infra.md

运行：
    cd idbackend && pytest tests/test_contextvar_infra.py -v
"""
import inspect
import pytest
import pytest_asyncio
from sqlalchemy import Column, Integer, String, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

from src.infra.database import (
    get_db,
    get_db_context,
    get_current_db,
    _db_session_var,
)


# ─── 最小化测试 model ──────────────────────────────────────
ModelBase = declarative_base()


class TblContextVar(ModelBase):
    """测试表（纯 SQLite 兼容字段）。"""
    __tablename__ = "test_contextvar"

    id = Column(Integer, primary_key=True)
    name = Column(String(64), nullable=False, unique=True)
    value = Column(Integer, default=0)


# ─── 共享 fixture ───
@pytest_asyncio.fixture
async def test_engine():
    """每个测试一个共享内存 SQLite（用临时文件）。"""
    import tempfile
    tmpfile = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmpfile.close()
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmpfile.name}",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(ModelBase.metadata.create_all)
    yield engine
    await engine.dispose()
    import pathlib as _p
    _p.Path(tmpfile.name).unlink(missing_ok=True)


@pytest_asyncio.fixture
async def test_factory(test_engine):
    """提供 session 工厂。"""
    return async_sessionmaker(test_engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
def reset_contextvar():
    """每个测试前后 reset ContextVar。"""
    _db_session_var.set(None)
    yield
    _db_session_var.set(None)


@pytest.fixture(autouse=True)
def monkeypatch_async_session(test_factory, monkeypatch):
    """把 src.infra.database.AsyncSessionLocal 替换成 SQLite 测试 factory。

    这样测试时 get_db / get_db_context 不会去连真实 PG。
    """
    monkeypatch.setattr("src.infra.database.AsyncSessionLocal", test_factory)


# ════════════════════════════════════════════════════════════════
# 测试 1：未进入 get_db 时 get_current_db 抛 RuntimeError
# ════════════════════════════════════════════════════════════════
@pytest.mark.step1_ctx
@pytest.mark.asyncio
async def test_get_current_db_raises_outside_context():
    """ContextVar 未设置时，get_current_db 应抛 RuntimeError。"""
    with pytest.raises(RuntimeError, match="没有活动的 db session"):
        get_current_db()


# ════════════════════════════════════════════════════════════════
# 测试 2：Depends(get_db) 内可 get_current_db
# ════════════════════════════════════════════════════════════════
@pytest.mark.step1_ctx
@pytest.mark.asyncio
async def test_get_current_db_inside_get_db(test_factory):
    """Depends(get_db) 内调 get_current_db 应返回同一 session。"""
    async def fake_route():
        async for session in get_db():
            db1 = session
            db2 = get_current_db()
            assert db1 is db2, "ContextVar 应返回同一 session"

    await fake_route()
    # 退出后 ContextVar 应被 reset
    assert _db_session_var.get() is None


# ════════════════════════════════════════════════════════════════
# 测试 3：async with get_db_context 内可 get_current_db
# ════════════════════════════════════════════════════════════════
@pytest.mark.step1_ctx
@pytest.mark.asyncio
async def test_get_current_db_inside_context():
    """get_db_context 内调 get_current_db 应返回当前 session。"""
    async with get_db_context() as db1:
        db2 = get_current_db()
        assert db1 is db2, "ContextVar 应返回同一 session"

    # 退出后 ContextVar 应被 reset
    assert _db_session_var.get() is None


# ════════════════════════════════════════════════════════════════
# 测试 4：异常路径下 ContextVar 也被 reset
# ════════════════════════════════════════════════════════════════
@pytest.mark.step1_ctx
@pytest.mark.asyncio
async def test_contextvar_reset_on_exception():
    """业务抛异常后，ContextVar 必须被 reset（不留污染）。"""
    with pytest.raises(ValueError):
        async with get_db_context():
            raise ValueError("业务异常")

    assert _db_session_var.get() is None, "异常路径必须 reset ContextVar"


# ════════════════════════════════════════════════════════════════
# 测试 5：嵌套 get_db_context：内层退出后外层恢复
# ════════════════════════════════════════════════════════════════
@pytest.mark.step1_ctx
@pytest.mark.asyncio
async def test_nested_get_db_context():
    """嵌套进入：内层退出后，外层 session 自动可见。"""
    async with get_db_context() as outer_db:
        assert get_current_db() is outer_db

        async with get_db_context() as inner_db:
            assert get_current_db() is inner_db
            assert inner_db is not outer_db

        # 内层退出 → ContextVar 恢复为 outer_db
        assert get_current_db() is outer_db

    # 外层退出 → ContextVar 复位 None
    assert _db_session_var.get() is None


# ════════════════════════════════════════════════════════════════
# 测试 6：get_db 内业务正常 → 数据落盘
# ════════════════════════════════════════════════════════════════
@pytest.mark.step1_ctx
@pytest.mark.asyncio
async def test_get_db_commit_via_contextvar(test_factory):
    """get_db 内通过 ContextVar 拿 session，commit 后数据落盘。"""

    async def fake_route():
        async for _ in get_db():
            db = get_current_db()  # 内部取
            db.add(TblContextVar(name="via_contextvar", value=42))

    await fake_route()

    # 验证落盘
    async with test_factory() as verify:
        result = await verify.execute(
            select(TblContextVar).where(TblContextVar.name == "via_contextvar")
        )
        obj = result.scalar_one_or_none()
        assert obj is not None
        assert obj.value == 42


# ════════════════════════════════════════════════════════════════
# 测试 7：get_db 内业务异常 → 数据回滚
# ════════════════════════════════════════════════════════════════
@pytest.mark.step1_ctx
@pytest.mark.asyncio
async def test_get_db_rollback_via_contextvar(test_factory):
    """get_db 内抛异常 → rollback → 数据不落盘。"""

    async def fake_route():
        async for _ in get_db():
            db = get_current_db()
            db.add(TblContextVar(name="should_rollback", value=99))
            raise ValueError("主动抛异常")

    with pytest.raises(ValueError):
        await fake_route()

    # 验证回滚
    async with test_factory() as verify:
        result = await verify.execute(
            select(TblContextVar).where(TblContextVar.name == "should_rollback")
        )
        assert result.scalar_one_or_none() is None


# ════════════════════════════════════════════════════════════════
# 测试 8：get_db_context 内部异常也走 rollback
# ════════════════════════════════════════════════════════════════
@pytest.mark.step1_ctx
@pytest.mark.asyncio
async def test_get_db_context_rollback_via_contextvar(test_factory):
    """get_db_context 内业务异常 → rollback。"""

    with pytest.raises(ValueError):
        async with get_db_context() as db:
            db.add(TblContextVar(name="ctx_rollback", value=1))
            raise ValueError("业务异常")

    async with test_factory() as verify:
        result = await verify.execute(
            select(TblContextVar).where(TblContextVar.name == "ctx_rollback")
        )
        assert result.scalar_one_or_none() is None


# ════════════════════════════════════════════════════════════════
# 测试 9：ContextVar 与 yield session 同一对象
# ════════════════════════════════════════════════════════════════
@pytest.mark.step1_ctx
@pytest.mark.asyncio
async def test_contextvar_is_same_as_yielded():
    """ContextVar 中的 session 与 yield 出的 session 是同一对象。"""
    captured = {}

    async def fake_route():
        async for session in get_db():
            captured["yielded"] = session
            captured["contextvar"] = get_current_db()

    await fake_route()
    assert captured["yielded"] is captured["contextvar"]


# ════════════════════════════════════════════════════════════════
# 测试 10：get_current_db 源码中定义（防止丢失 API）
# ════════════════════════════════════════════════════════════════
@pytest.mark.step1_ctx
def test_get_current_db_exists():
    """get_current_db 必须在 database.py 中定义。"""
    assert callable(get_current_db)
    assert "db session" in get_current_db.__doc__ or "ContextVar" in (get_current_db.__doc__ or "")


# ════════════════════════════════════════════════════════════════
# 测试 11：_db_session_var 必须是 ContextVar 类型
# ════════════════════════════════════════════════════════════════
@pytest.mark.step1_ctx
def test_db_session_var_is_contextvar():
    """_db_session_var 必须是 ContextVar 实例。"""
    from contextvars import ContextVar
    assert isinstance(_db_session_var, ContextVar)


# ════════════════════════════════════════════════════════════════
# 测试 12：get_db 内部源码包含 ContextVar set/reset
# ════════════════════════════════════════════════════════════════
@pytest.mark.step1_ctx
def test_get_db_uses_contextvar():
    """get_db 内部源码必须包含 _db_session_var.set 和 reset。"""
    src = inspect.getsource(get_db)
    assert "_db_session_var.set" in src, "get_db 必须 set ContextVar"
    assert "_db_session_var.reset" in src, "get_db 必须 reset ContextVar"


@pytest.mark.step1_ctx
def test_get_db_context_uses_contextvar():
    """get_db_context 内部源码必须包含 _db_session_var.set 和 reset。"""
    src = inspect.getsource(get_db_context)
    assert "_db_session_var.set" in src, "get_db_context 必须 set ContextVar"
    assert "_db_session_var.reset" in src, "get_db_context 必须 reset ContextVar"
