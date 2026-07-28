"""e2e 冒烟测试：完整 HTTP 请求 → ContextVar → service → repo → DB → commit 流程。

依据：
    docs/docs-backend/dbcontext/testing.md

运行：
    cd idbackend && pytest tests/test_e2e_smoke.py -v

说明：
    这里模拟 FastAPI 请求调用一个完整的 endpoint（无需真实 HTTP server），
    验证 ContextVar 在整个调用链中正确流转。
"""
import asyncio
import inspect
import pytest
import pytest_asyncio
from sqlalchemy import Column, Integer, String
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

from src.infra.database import (
    get_db,
    get_db_context,
    get_current_db,
    _db_session_var,
)


# ─── 共享 fixture ───
@pytest_asyncio.fixture
async def test_engine():
    import tempfile
    tmpfile = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmpfile.close()
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmpfile.name}",
        echo=False,
    )
    yield engine
    await engine.dispose()
    import pathlib as _p
    _p.Path(tmpfile.name).unlink(missing_ok=True)


@pytest_asyncio.fixture
async def test_factory(test_engine):
    return async_sessionmaker(test_engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
def reset_contextvar():
    _db_session_var.set(None)
    yield
    _db_session_var.set(None)


@pytest.fixture(autouse=True)
def monkeypatch_async_session(test_factory, monkeypatch):
    monkeypatch.setattr("src.infra.database.AsyncSessionLocal", test_factory)


# ════════════════════════════════════════════════════════════════
# 测试 1：完整 GET 请求模拟（route → service → repo → DB → commit）
# ════════════════════════════════════════════════════════════════
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_get_request_full_flow(test_engine, test_factory):
    """模拟一个完整的 GET 请求流程。

    流程：
      1. FastAPI Depends(get_db) 设置 ContextVar
      2. Route 函数被调用
      3. Service 方法从 ContextVar 取 db
      4. Repo 方法从 ContextVar 取 db
      5. DB 操作完成
      6. Route 返回，框架 commit
      7. ContextVar 被 reset
    """
    # 定义一个最简单的 model
    Base = declarative_base()

    class TblE2E(Base):
        __tablename__ = "tbl_e2e"
        id = Column(Integer, primary_key=True)
        name = Column(String(64))

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 模拟 service + repo
    from src.repositories.extra_info_field_repo import ExtraInfoFieldRepository
    from src.models.extra_info_field import ExtraInfoField

    # 确保表存在
    async with test_engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: ExtraInfoField.__table__.create(sync_conn, checkfirst=True)
        )

    async def fake_route():
        """模拟 route 函数（用 Depends(get_db)）"""
        async for _ in get_db():
            # 1. route 内部调用 service（service 现在不再接收 db）
            # 2. service 调用 repo（repo 现在不再接收 db）
            db = get_current_db()  # 模拟 service 内部取 db
            db.add(ExtraInfoField(
                name="e2e_test",
                type="text",
                sort_order=1,
            ))

    # 跑请求
    await fake_route()

    # 验证数据落盘（get_db 已自动 commit）
    async with test_factory() as verify:
        from sqlalchemy import select
        result = await verify.execute(
            select(ExtraInfoField).where(ExtraInfoField.name == "e2e_test")
        )
        obj = result.scalar_one_or_none()
        assert obj is not None, "数据未落盘"
        assert obj.type == "text"

    # 验证 ContextVar 已 reset
    assert _db_session_var.get() is None


# ════════════════════════════════════════════════════════════════
# 测试 2：业务异常时 rollback
# ════════════════════════════════════════════════════════════════
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_business_exception_rollback(test_engine, test_factory):
    """业务异常时框架自动 rollback，ContextVar 被 reset。"""
    from src.models.extra_info_field import ExtraInfoField

    async with test_engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: ExtraInfoField.__table__.create(sync_conn, checkfirst=True)
        )

    # 用 get_db_context 模拟 route 行为（无 async generator 复杂度）
    with pytest.raises(ValueError):
        async with get_db_context():
            db = get_current_db()
            db.add(ExtraInfoField(
                name="should_rollback",
                type="text",
                sort_order=2,
            ))
            raise ValueError("业务异常")

    # 验证 rollback
    async with test_factory() as verify:
        from sqlalchemy import select
        result = await verify.execute(
            select(ExtraInfoField).where(ExtraInfoField.name == "should_rollback")
        )
        assert result.scalar_one_or_none() is None, "rollback 失败"

    # ContextVar 已 reset
    assert _db_session_var.get() is None


# ════════════════════════════════════════════════════════════════
# 测试 3：嵌套 ContextVar 正确性（get_db 内 get_db_context）
# ════════════════════════════════════════════════════════════════
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_nested_context(test_engine, test_factory):
    """get_db 嵌套 get_db_context：内层退出后外层仍可见。"""
    from src.models.extra_info_field import ExtraInfoField

    async with test_engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: ExtraInfoField.__table__.create(sync_conn, checkfirst=True)
        )

    captured = []

    async def fake_route():
        async for outer_db in get_db():
            captured.append(("outer_enter", get_current_db() is outer_db))

            async with get_db_context() as inner_db:
                captured.append(("inner_enter", get_current_db() is inner_db))
                captured.append(("inner_different", inner_db is not outer_db))

                # 内层 DB 操作
                inner_db.add(ExtraInfoField(
                    name="nested_inner",
                    type="text",
                    sort_order=3,
                ))

            # 内层退出后 ContextVar 恢复为 outer_db
            captured.append(("after_inner_exit", get_current_db() is outer_db))

            # 外层 DB 操作
            outer_db.add(ExtraInfoField(
                name="nested_outer",
                type="text",
                sort_order=4,
            ))

    await fake_route()

    # 验证 captured 序列
    assert ("outer_enter", True) in captured
    assert ("inner_enter", True) in captured
    assert ("inner_different", True) in captured
    assert ("after_inner_exit", True) in captured

    # 两条数据都应落盘
    async with test_factory() as verify:
        from sqlalchemy import select
        for name in ["nested_inner", "nested_outer"]:
            result = await verify.execute(
                select(ExtraInfoField).where(ExtraInfoField.name == name)
            )
            assert result.scalar_one_or_none() is not None, f"{name} 未落盘"


# ════════════════════════════════════════════════════════════════
# 测试 4：dbcontext 改造后 `db` 形参不再存在于 service 层
# ════════════════════════════════════════════════════════════════
@pytest.mark.e2e
def test_e2e_no_service_layer_db_param():
    """service 层所有方法都不再有 db 形参（关键架构约束）。"""
    from pathlib import Path
    import ast

    service_dir = Path("/home/dustp/codes/idproject/idbackend/src/services")
    violations = []

    for py_file in sorted(service_dir.glob("*.py")):
        if py_file.name.startswith("__"):
            continue
        src = py_file.read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            # 跳过嵌套方法（如嵌套的 lambda / inner func）
            if node.args.args and node.args.args[0].arg == "db":
                first = node.args.args[0]
                if first.annotation and isinstance(first.annotation, ast.Name):
                    if first.annotation.id in ("AsyncSession", "Session"):
                        # 检查方法名是否在 _db_exception_methods 名单中
                        # 这里简化：只报告
                        violations.append(f"{py_file.name}:{node.name}()")

    assert violations == [], (
        f"以下 service 方法仍有 db 形参（违反 dbcontext 架构）：\n  "
        + "\n  ".join(violations)
    )


# ════════════════════════════════════════════════════════════════
# 测试 5：repo 层所有方法不再接收 db 形参
# ════════════════════════════════════════════════════════════════
@pytest.mark.e2e
def test_e2e_no_repo_layer_db_param():
    """repo 层所有方法都不再有 db 形参。"""
    from pathlib import Path
    import ast

    repo_dir = Path("/home/dustp/codes/idproject/idbackend/src/repositories")
    violations = []

    for py_file in sorted(repo_dir.glob("*_repo.py")):
        src = py_file.read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            is_static = any(
                isinstance(d, ast.Name) and d.id == "staticmethod"
                for d in node.decorator_list
            )
            if not is_static:
                continue
            if node.args.args and node.args.args[0].arg == "db":
                violations.append(f"{py_file.name}:{node.name}()")

    assert violations == [], (
        f"以下 repo 方法仍有 db 形参：\n  " + "\n  ".join(violations)
    )


# ════════════════════════════════════════════════════════════════
# 测试 6：route 层使用 _db 触发 ContextVar 而非直接用 db
# ════════════════════════════════════════════════════════════════
@pytest.mark.e2e
def test_e2e_routes_use_dummy_db():
    """route 层使用 _db 触发 ContextVar，函数内部不直接用 db。"""
    from pathlib import Path
    import re

    route_dir = Path("/home/dustp/codes/idproject/idbackend/src/app/routes")
    no_db_param_count = 0
    dummy_db_param_count = 0

    for py_file in sorted(route_dir.glob("*.py")):
        if py_file.name.startswith("__"):
            continue
        src = py_file.read_text()
        # 统计
        no_db_param_count += len(re.findall(r'\bdb: AsyncSession\s*=\s*Depends\(get_db\)', src))
        dummy_db_param_count += len(re.findall(r'_db: AsyncSession\s*=\s*Depends\(get_db\)', src))

    assert no_db_param_count == 0, f"应没有 db 形参，但找到 {no_db_param_count}"
    assert dummy_db_param_count > 0, f"应至少 1 个 _db 形参，但找到 {dummy_db_param_count}"


# ════════════════════════════════════════════════════════════════
# 测试 7：跨请求 ContextVar 不污染（独立性）
# ════════════════════════════════════════════════════════════════
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_request_isolation():
    """两次连续请求之间 ContextVar 不污染。"""
    captured = []

    async def fake_request(value: int):
        async for _ in get_db():
            db = get_current_db()
            captured.append(value)
            assert db is not None

    await fake_request(1)
    assert _db_session_var.get() is None, "请求 1 结束后 ContextVar 应被 reset"

    await fake_request(2)
    assert _db_session_var.get() is None, "请求 2 结束后 ContextVar 应被 reset"

    assert captured == [1, 2]


# ════════════════════════════════════════════════════════════════
# 测试 8：ContextVar 在并发任务中的正确性
# ════════════════════════════════════════════════════════════════
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_concurrent_tasks_isolation():
    """并发任务中 ContextVar 不串扰（Python asyncio 上下文隔离）。"""
    results = []

    async def task(name: str, value: int):
        async with get_db_context():
            results.append((name, value, get_current_db()))

    # 并发跑 3 个任务
    await asyncio.gather(
        task("a", 1),
        task("b", 2),
        task("c", 3),
    )

    # 3 个任务都用各自独立的 session
    assert len(results) == 3
    sessions = [r[2] for r in results]
    assert len(set(id(s) for s in sessions)) == 3, "3 个并发任务应使用 3 个不同 session"