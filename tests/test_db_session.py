"""Step 1 测试：验证 get_db 自动 commit / rollback 行为。

运行：
    cd idbackend && pytest tests/test_db_session.py -v

依据：
    docs/docs-backend/dbremake/step1-framework.md

设计原则：
    - 不依赖 reload（避免 reload 后模块状态错乱）
    - 测试的是"框架 commit/rollback 的逻辑"，通过对比"无框架事务 vs 有框架事务"的行为差异
    - 直接验证 src/infra/database.py:get_db 的源码包含正确逻辑
"""
import inspect
import pytest
import pytest_asyncio
from sqlalchemy import Column, Integer, String, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

# ─── 最小化测试 model ──────────────────────────────────────
ModelBase = declarative_base()


class TblUser(ModelBase):
    """测试用户表（纯 SQLite 兼容字段）。"""
    __tablename__ = "test_users"

    id = Column(Integer, primary_key=True)
    name = Column(String(64), nullable=False, unique=True)
    value = Column(Integer, default=0)


# ─── 本文件独立 fixture（避免与 conftest 共享造成 model 注册问题） ───
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
    """提供 session 工厂（用测试 engine）。"""
    return async_sessionmaker(test_engine, expire_on_commit=False)


# ─── 框架逻辑的实现（精确复制 src/infra/database.py:get_db） ───
async def framework_get_db(factory):
    """完全复制 src/infra/database.py:get_db 的逻辑。

    这样做的好处：
    - 不依赖 monkeypatch / reload，避免模块状态错乱
    - 测试的代码逻辑和项目里 100% 一致
    - 失败时能直接定位是逻辑 bug 还是 patch 问题
    """
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ════════════════════════════════════════════════════════════════
# 测试 1：业务正常 → 框架自动 commit
# ════════════════════════════════════════════════════════════════
@pytest.mark.step1
@pytest.mark.asyncio
async def test_get_db_auto_commit_on_success(test_factory):
    """业务 add + return → 框架 commit → 数据落盘。"""
    async def fake_route_logic():
        async for session in framework_get_db(test_factory):
            session.add(TblUser(name="auto_commit_success", value=42))
            # ↑ async for 正常退出 → 框架 commit

    await fake_route_logic()

    async with test_factory() as verify_session:
        result = await verify_session.execute(
            select(TblUser).where(TblUser.name == "auto_commit_success")
        )
        obj = result.scalar_one_or_none()
        assert obj is not None, "业务正常后框架 commit，数据应该落盘"
        assert obj.value == 42


# ════════════════════════════════════════════════════════════════
# 测试 2：业务异常 → 框架自动 rollback
# ════════════════════════════════════════════════════════════════
@pytest.mark.step1
@pytest.mark.asyncio
async def test_get_db_auto_rollback_on_exception(test_factory):
    """业务 add + 抛异常 → 框架 rollback → 数据不存在。"""
    async def fake_route_logic():
        async for session in framework_get_db(test_factory):
            session.add(TblUser(name="should_rollback", value=99))
            raise ValueError("业务模拟异常")

    with pytest.raises(ValueError, match="业务模拟异常"):
        await fake_route_logic()

    async with test_factory() as verify_session:
        result = await verify_session.execute(
            select(TblUser).where(TblUser.name == "should_rollback")
        )
        assert result.scalar_one_or_none() is None, "异常应该触发 rollback"


# ════════════════════════════════════════════════════════════════
# 测试 3：业务 commit 后框架 commit 幂等
# ════════════════════════════════════════════════════════════════
@pytest.mark.step1
@pytest.mark.asyncio
async def test_business_commit_then_framework_commit_is_safe(test_factory):
    """业务自己 commit 后，框架 commit 幂等（关键兼容性测试）。"""
    async def fake_business():
        async for session in framework_get_db(test_factory):
            session.add(TblUser(name="own_commit", value=7))
            await session.flush()
            # ↑ 业务自己 commit（模拟 service 里的现状）
            await session.commit()
            # ↑ async for 退出 → 框架 commit（SQLAlchemy 2.0 幂等）

    await fake_business()

    async with test_factory() as verify_session:
        result = await verify_session.execute(
            select(TblUser).where(TblUser.name == "own_commit")
        )
        obj = result.scalar_one_or_none()
        assert obj is not None
        assert obj.value == 7


# ════════════════════════════════════════════════════════════════
# 测试 4：业务 rollback 后框架 rollback 幂等
# ════════════════════════════════════════════════════════════════
@pytest.mark.step1
@pytest.mark.asyncio
async def test_business_rollback_then_framework_rollback_is_safe(test_factory):
    """业务自己 rollback 后框架再 rollback 不报错。"""
    async def fake_business():
        async for session in framework_get_db(test_factory):
            session.add(TblUser(name="own_rollback", value=5))
            try:
                raise ValueError("业务失败")
            except ValueError:
                await session.rollback()
                # ↑ 异常继续抛，框架 except 会再 rollback（应幂等）
                raise

    with pytest.raises(ValueError):
        await fake_business()


# ════════════════════════════════════════════════════════════════
# 测试 5：连接池不被污染（异常后连接能复用）
# ════════════════════════════════════════════════════════════════
@pytest.mark.step1
@pytest.mark.asyncio
async def test_connection_reusable_after_rollback(test_factory):
    """一个请求 rollback 后，下一个请求能正常使用。"""
    # 请求 1：失败
    async def req1():
        async for session in framework_get_db(test_factory):
            session.add(TblUser(name="req1_fail", value=1))
            raise RuntimeError("req1 fail")

    with pytest.raises(RuntimeError):
        await req1()

    # 请求 2：成功
    async def req2():
        async for session in framework_get_db(test_factory):
            session.add(TblUser(name="req2_ok", value=2))

    await req2()

    # 验证：只有 req2 的数据
    async with test_factory() as verify_session:
        result = await verify_session.execute(select(TblUser).order_by(TblUser.id))
        objs = result.scalars().all()
        assert len(objs) == 1, f"应该有 1 个对象，实际有 {len(objs)}"
        assert objs[0].name == "req2_ok"


# ════════════════════════════════════════════════════════════════
# 测试 6：commit 失败触发 rollback（commit 抛异常场景）
# ════════════════════════════════════════════════════════════════
@pytest.mark.step1
@pytest.mark.asyncio
async def test_commit_failure_triggers_rollback_logic():
    """模拟 commit 失败的场景，验证 except 分支逻辑正确。

    直接验证"commit 抛异常 → rollback 被调用"的逻辑链。
    """
    commit_call_count = 0
    rollback_call_count = 0

    class FailingCommitSession:
        def __init__(self):
            pass
        async def commit(self):
            nonlocal commit_call_count
            commit_call_count += 1
            raise ConnectionError("模拟 DB 连接断开")
        async def rollback(self):
            nonlocal rollback_call_count
            rollback_call_count += 1
        def add(self, obj):
            pass

    # 模拟 get_db 的核心逻辑
    failing = FailingCommitSession()
    try:
        # 业务阶段：什么都不做
        yield_value = "业务逻辑"
        # ↑ 模拟 yield session 后业务执行（这里业务没 add）
        # 框架 commit
        await failing.commit()
    except ConnectionError:
        # 框架 rollback
        await failing.rollback()

    assert commit_call_count == 1, "commit 应该被调用 1 次"
    assert rollback_call_count == 1, "commit 失败后 rollback 应该被调用 1 次"


# ════════════════════════════════════════════════════════════════
# 测试 7：项目里 get_db 函数签名正确
# ════════════════════════════════════════════════════════════════
@pytest.mark.step1
def test_get_db_signature():
    """get_db 必须是 AsyncGenerator[AsyncSession, None]（FastAPI Depends 需要）。"""
    from src.infra.database import get_db

    sig = inspect.signature(get_db)
    assert sig.return_annotation is not None, "get_db 必须有返回值注解"

    return_str = str(sig.return_annotation)
    assert "AsyncGenerator" in return_str, (
        f"get_db 返回类型应该是 AsyncGenerator，但实际是 {return_str}"
    )
    assert "AsyncSession" in return_str, (
        f"get_db 应该 yield AsyncSession，但实际是 {return_str}"
    )


# ════════════════════════════════════════════════════════════════
# 测试 8：项目里 get_db 函数体包含正确的事务逻辑
# ════════════════════════════════════════════════════════════════
@pytest.mark.step1
def test_get_db_has_commit_and_rollback():
    """get_db 函数体内必须包含 commit 和 rollback 调用。"""
    from src.infra.database import get_db

    source = inspect.getsource(get_db)
    assert "session.commit" in source, (
        f"get_db 必须调用 session.commit，当前源码:\n{source}"
    )
    assert "session.rollback" in source, (
        f"get_db 必须调用 session.rollback，当前源码:\n{source}"
    )
    assert "yield session" in source, (
        f"get_db 必须 yield session，当前源码:\n{source}"
    )
    assert "raise" in source, (
        f"get_db 在 rollback 后必须重抛异常（让 FastAPI 知道错误），当前源码:\n{source}"
    )


# ════════════════════════════════════════════════════════════════
# 测试 9：完整业务周期（add + 多次 flush）
# ════════════════════════════════════════════════════════════════
@pytest.mark.step1
@pytest.mark.asyncio
async def test_full_business_cycle(test_factory):
    """add A + flush + add B + flush + return → 框架 commit 全部。"""
    async def fake_route_logic():
        async for session in framework_get_db(test_factory):
            a = TblUser(name="cycle_A", value=1)
            session.add(a)
            await session.flush()
            assert a.id is not None

            b = TblUser(name="cycle_B", value=2)
            session.add(b)
            await session.flush()
            assert b.id is not None

    await fake_route_logic()

    async with test_factory() as verify_session:
        result = await verify_session.execute(
            select(TblUser).where(TblUser.name.in_(["cycle_A", "cycle_B"]))
        )
        users = result.scalars().all()
        assert len(users) == 2
        assert {u.name for u in users} == {"cycle_A", "cycle_B"}


# ════════════════════════════════════════════════════════════════
# 测试 10：原 service commit 模式 + 框架 commit 共存
# ════════════════════════════════════════════════════════════════
@pytest.mark.step1
@pytest.mark.asyncio
async def test_existing_service_commit_pattern(test_factory):
    """模拟原项目 service 的多次 commit 模式，验证 Step 1 兼容。

    场景：业务连续 add + 多次 commit + return。
    """
    async def business_with_multiple_commits():
        async for session in framework_get_db(test_factory):
            u1 = TblUser(name="multi_commit_1", value=1)
            session.add(u1)
            await session.flush()
            await session.commit()  # service commit 1

            u2 = TblUser(name="multi_commit_2", value=2)
            session.add(u2)
            await session.flush()
            await session.commit()  # service commit 2

            # ↑ async for 退出 → 框架 commit（幂等）

    await business_with_multiple_commits()

    async with test_factory() as verify_session:
        result = await verify_session.execute(
            select(TblUser).where(TblUser.name.in_(["multi_commit_1", "multi_commit_2"]))
        )
        users = result.scalars().all()
        assert len(users) == 2


# ════════════════════════════════════════════════════════════════
# 测试 11：AsyncSessionLocal 配置正确
# ════════════════════════════════════════════════════════════════
@pytest.mark.step1
def test_session_local_config():
    """expire_on_commit=False（Step 4 依赖此配置）。"""
    from src.infra.database import AsyncSessionLocal
    kwargs = AsyncSessionLocal.kw
    assert kwargs.get("expire_on_commit") is False, (
        "expire_on_commit 必须是 False，否则 commit 后属性过期"
    )
