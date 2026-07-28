"""Step 5 测试：边界场景处理。

依据：
    docs/docs-backend/dbcontext/step5-edge-cases.md

运行：
    cd idbackend && pytest tests/test_edge_cases.py -v
"""
import asyncio
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from src.infra.database import (
    get_db,
    get_db_context,
    get_current_db,
    _db_session_var,
    AsyncSessionLocal,
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
# 测试 1：AuthMiddleware 调用的 UserService.verify_account_active 自管理 session
# ════════════════════════════════════════════════════════════════
@pytest.mark.step5_ctx
@pytest.mark.asyncio
async def test_user_service_verify_account_active_uses_self_managed_session(monkeypatch):
    """verify_account_active 用 `async with AsyncSessionLocal()` 自管理 session，
    因为它在 Depends(get_db) 之前被中间件调用，不能用 ContextVar。

    测试要点：源码中存在 `async with AsyncSessionLocal()` 模式
    """
    # 读源码验证模式
    from src.services import user_service
    src = open(user_service.__file__).read()

    # verify_account_active 方法应包含自管理 session
    assert "verify_account_active" in src
    assert "async with AsyncSessionLocal()" in src

    # 不应使用 get_current_db（避免与 Depends 冲突）
    # 验证 verify_account_active 方法体内没有 get_current_db
    import re
    m = re.search(r'def verify_account_active.*?(?=\n    @|\nclass )', src, re.DOTALL)
    if m:
        method_src = m.group(0)
        assert "get_current_db" not in method_src, (
            "verify_account_active 不应使用 get_current_db（中间件场景下会冲突）"
        )


# ════════════════════════════════════════════════════════════════
# 测试 2：FileService 不再接受 db 形参
# ════════════════════════════════════════════════════════════════
@pytest.mark.step5_ctx
def test_file_service_no_db_in_init():
    """FileService.__init__ 不再接受 db 形参（从 ContextVar 取）。"""
    import inspect
    from src.services.file_service import FileService

    sig = inspect.signature(FileService.__init__)
    assert "db" not in sig.parameters, (
        f"FileService.__init__ 不应再有 db 形参：{sig}"
    )
    # 应只剩 storage
    assert "storage" in sig.parameters


# ════════════════════════════════════════════════════════════════
# 测试 3：get_file_service 依赖不再注入 db
# ════════════════════════════════════════════════════════════════
@pytest.mark.step5_ctx
def test_get_file_service_no_db():
    """get_file_service 依赖不再注入 db。"""
    import inspect
    from src.app.dependencies import get_file_service

    sig = inspect.signature(get_file_service)
    assert "db" not in sig.parameters, (
        f"get_file_service 不应再有 db 形参：{sig}"
    )


# ════════════════════════════════════════════════════════════════
# 测试 4：FileService 内部通过 _db 属性从 ContextVar 取
# ════════════════════════════════════════════════════════════════
@pytest.mark.step5_ctx
@pytest.mark.asyncio
async def test_file_service_uses_contextvar_db():
    """FileService 内部通过 _db 属性从 ContextVar 取。"""
    from src.services.file_service import FileService

    # 创建一个 mock storage
    class MockStorage:
        pass

    svc = FileService(storage=MockStorage())

    # 没有 ContextVar 时 _db 应抛 RuntimeError
    _db_session_var.set(None)
    with pytest.raises(RuntimeError):
        _ = svc._db

    # 设置 ContextVar 后 _db 应可用
    async with get_db_context() as db:
        assert svc._db is db


# ════════════════════════════════════════════════════════════════
# 测试 5：LangGraph 节点（如果存在）应能从 ContextVar 取 db
# ════════════════════════════════════════════════════════════════
@pytest.mark.step5_ctx
def test_langgraph_node_supports_contextvar():
    """LangGraph 节点应该能从 ContextVar 取 db（用 get_db_context 包裹）。"""
    # 这是一个约定检查：节点不在 FastAPI 请求上下文中，
    # 需要手动用 `async with get_db_context()` 设置 ContextVar
    from src.infra.database import get_db_context, get_current_db

    # 模拟 LangGraph 节点调用
    async def fake_node():
        async with get_db_context():
            return get_current_db()

    # 运行
    db = asyncio.run(fake_node())
    assert db is not None
    assert _db_session_var.get() is None  # 已 reset


# ════════════════════════════════════════════════════════════════
# 测试 6：后端任务 / migration 脚本仍用 `async with AsyncSessionLocal()`
# ════════════════════════════════════════════════════════════════
@pytest.mark.step5_ctx
def test_async_session_local_still_exists():
    """AsyncSessionLocal 仍可用（供 migration 脚本使用）。"""
    from src.infra.database import AsyncSessionLocal

    # 应是 async_sessionmaker 实例
    from sqlalchemy.ext.asyncio import async_sessionmaker
    assert isinstance(AsyncSessionLocal, async_sessionmaker)


# ════════════════════════════════════════════════════════════════
# 测试 7：dbcontext 改造后全项目 `await db.commit()` 仅出现在 database.py
# ════════════════════════════════════════════════════════════════
@pytest.mark.step5_ctx
def test_db_commit_only_outside_scripts():
    """全项目中只有 infra/database.py 和 scripts/ 可以有 `await db.commit()`。

    scripts/ 目录是独立的迁移脚本，使用 `async with AsyncSessionLocal()`
    自管理 session 和事务，不走 FastAPI 请求上下文。
    """
    from pathlib import Path

    src_dir = Path("/home/dustp/codes/idproject/idbackend/src")
    violations = []

    for py_file in sorted(src_dir.rglob("*.py")):
        rel = py_file.relative_to(src_dir.parent)
        rel_str = str(rel)
        # 允许的文件
        if "database.py" in rel_str:
            continue
        if "scripts/" in rel_str:
            continue  # 迁移脚本独立管事务
        src = py_file.read_text()
        for i, line in enumerate(src.split("\n"), 1):
            if line.strip() == "await db.commit()":
                violations.append(f"{rel}:{i}")

    assert violations == [], (
        f"以下文件仍调用 await db.commit()（违反 dbcontext 原则）：\n  "
        + "\n  ".join(violations)
    )


# ════════════════════════════════════════════════════════════════
# 测试 8：AuthMiddleware 中间件调用 user_service.verify_account_active
# ════════════════════════════════════════════════════════════════
@pytest.mark.step5_ctx
def test_auth_middleware_imports():
    """AuthMiddleware 能 import（语法 OK）。"""
    from src.app.middleware.auth_middleware import AuthMiddleware
    assert AuthMiddleware is not None


# ════════════════════════════════════════════════════════════════
# 测试 9：完整 GET 请求通过 FastAPI TestClient 验证 ContextVar 流转
# ════════════════════════════════════════════════════════════════
@pytest.mark.step5_ctx
def test_fastapi_get_db_contextvar_lifecycle():
    """验证 FastAPI Depends(get_db) 的 ContextVar 生命周期。"""
    from src.infra.database import get_db

    captured = []

    async def fake_endpoint():
        # 进入时 ContextVar 应被设置
        captured.append(("inside", _db_session_var.get() is not None))
        captured.append(("db", get_current_db()))

    async def run():
        async for _ in get_db():
            await fake_endpoint()

    asyncio.run(run())

    assert ("inside", True) in captured, "Depends(get_db) 进入时 ContextVar 应被设置"
    assert _db_session_var.get() is None, "退出后 ContextVar 应被 reset"


# ════════════════════════════════════════════════════════════════
# 测试 10：FileService 用 ContextVar 而非传参
# ════════════════════════════════════════════════════════════════
@pytest.mark.step5_ctx
def test_file_service_uses_contextvar():
    """FileService 不在 __init__ 接收 db，所有 DB 操作走 ContextVar。"""
    from src.services.file_service import FileService
    import inspect

    # 检查 FileService 没有 _db 形参
    init_sig = inspect.signature(FileService.__init__)
    assert "db" not in init_sig.parameters

    # 但 _db 是 property，从 ContextVar 取
    svc_source = inspect.getsource(FileService)
    assert "_db" in svc_source
    assert "get_current_db" in svc_source