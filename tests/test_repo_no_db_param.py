"""Step 2 测试：验证 repo 不再接收 db 形参，改为 ContextVar 取 db。

依据：
    docs/docs-backend/dbcontext/step2-repo-no-db-param.md

运行：
    cd idbackend && pytest tests/test_repo_no_db_param.py -v

说明：
    Step 2 改造后所有 repo 方法从 ContextVar 取 db。本测试在 SQLite 上
    验证 4 件事：
    1. repo 方法签名无 db 形参
    2. repo 内部用 get_current_db()
    3. 在 get_db_context() 上下文内调用 repo 正常工作
    4. repo 内部不再有 await db.commit()
"""
import asyncio
import inspect
import pytest
import pytest_asyncio
from sqlalchemy import Column, Integer, String, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

from src.infra.database import get_db_context, _db_session_var, get_current_db


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
    """把 src.infra.database.AsyncSessionLocal 替换成 SQLite 测试 factory。

    这样 get_db / get_db_context 在测试时不会去连真实 PG。
    """
    monkeypatch.setattr("src.infra.database.AsyncSessionLocal", test_factory)


# ════════════════════════════════════════════════════════════════
# 测试 1：所有 repo 的 async 方法不再有 db 形参
# ════════════════════════════════════════════════════════════════
@pytest.mark.step2_ctx
def test_no_repo_method_takes_db_param():
    """所有 repo 的 async 方法都不应再有 db: AsyncSession 形参。

    检查方式：扫描 src/repositories/，找到所有 @staticmethod async def，
    其第一个形参不应是 db。
    """
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
# 测试 2：repo 内部用 get_current_db() 拿 db（静态分析）
# ════════════════════════════════════════════════════════════════
@pytest.mark.step2_ctx
def test_repo_uses_get_current_db():
    """每个 repo 的所有需要 db 的方法都应调 get_current_db()。"""
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
            func_src = ast.get_source_segment(src, node) or ""
            # 需要 db 的方法（方法体内有 await db.）
            if "await db." in func_src or "db.add" in func_src:
                if "get_current_db" not in func_src:
                    violations.append(f"{py_file.name}:{node.name}()")

    assert violations == [], (
        f"以下 repo 方法未调用 get_current_db()：\n  " + "\n  ".join(violations)
    )


# ════════════════════════════════════════════════════════════════
# 测试 3：ContextVar 未设置时调 repo → 抛 RuntimeError
# ════════════════════════════════════════════════════════════════
@pytest.mark.step2_ctx
@pytest.mark.asyncio
async def test_repo_call_without_context_raises():
    """ContextVar 未设置时调 repo 应抛 RuntimeError。"""
    from src.repositories.extra_info_field_repo import ExtraInfoFieldRepository

    # 确保 ContextVar 是 None
    _db_session_var.set(None)
    with pytest.raises(RuntimeError, match="没有活动的 db session"):
        await ExtraInfoFieldRepository.list_all()


# ════════════════════════════════════════════════════════════════
# 测试 4：repo 源码中不再出现 `await db.commit()`
# ════════════════════════════════════════════════════════════════
@pytest.mark.step2_ctx
def test_repo_no_await_db_commit():
    """repo 源码中不应有 `await db.commit()`（事务由框架管）。"""
    from pathlib import Path

    repo_dir = Path("/home/dustp/codes/idproject/idbackend/src/repositories")
    violations = []

    for py_file in sorted(repo_dir.glob("*_repo.py")):
        src = py_file.read_text()
        for i, line in enumerate(src.split("\n"), 1):
            if line.strip() == "await db.commit()":
                violations.append(f"{py_file.name}:{i}")

    assert violations == [], (
        f"以下 repo 仍有 await db.commit()（违反 dbcontext 原则）：\n  "
        + "\n  ".join(violations)
    )


# ════════════════════════════════════════════════════════════════
# 测试 5：repo 源码中不再出现 `db: AsyncSession` 形参
# ════════════════════════════════════════════════════════════════
@pytest.mark.step2_ctx
def test_repo_no_asyncsession_annotation():
    """repo 源码中不应再有 `db: AsyncSession` 形参注解。"""
    from pathlib import Path

    repo_dir = Path("/home/dustp/codes/idproject/idbackend/src/repositories")
    violations = []

    for py_file in sorted(repo_dir.glob("*_repo.py")):
        src = py_file.read_text()
        if "db: AsyncSession" in src:
            for i, line in enumerate(src.split("\n"), 1):
                if "db: AsyncSession" in line:
                    violations.append(f"{py_file.name}:{i}: {line.strip()}")

    assert violations == [], (
        f"以下 repo 仍有 db: AsyncSession 形参：\n  "
        + "\n  ".join(violations)
    )


# ════════════════════════════════════════════════════════════════
# 测试 6：repo 方法支持 kwargs-only 调用（不需要 db 形参）
# ════════════════════════════════════════════════════════════════
@pytest.mark.step2_ctx
@pytest.mark.asyncio
async def test_extra_info_field_repo_call_without_db(test_engine, test_factory):
    """extra_info_field_repo 是最简的 repo，可直接跑。"""
    from src.models.extra_info_field import ExtraInfoField
    from src.repositories.extra_info_field_repo import ExtraInfoFieldRepository
    from sqlalchemy import select

    # 创建表（用 engine.begin() 而不是 session.run_sync）
    async with test_engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: ExtraInfoField.__table__.create(sync_conn, checkfirst=True)
        )

    # 通过 ContextVar 调 repo
    async with get_db_context():
        await ExtraInfoFieldRepository.insert(
            name="测试字段",
            type="text",
            sort_order=1,
        )

    # 验证落盘
    async with test_factory() as verify:
        result = await verify.execute(
            select(ExtraInfoField).where(ExtraInfoField.name == "测试字段")
        )
        obj = result.scalar_one_or_none()
        assert obj is not None
        assert obj.type == "text"


# ════════════════════════════════════════════════════════════════
# 测试 7：repo 内的 rollback 不会污染 ContextVar
# ════════════════════════════════════════════════════════════════
@pytest.mark.step2_ctx
@pytest.mark.asyncio
async def test_repo_rollback_clears_contextvar():
    """业务异常 rollback 后，ContextVar 应被 reset。"""
    with pytest.raises(ValueError):
        async with get_db_context():
            raise ValueError("业务异常")

    assert _db_session_var.get() is None


# ════════════════════════════════════════════════════════════════
# 测试 8：repo 方法调用方式无 db 形参（签名检查）
# ════════════════════════════════════════════════════════════════
@pytest.mark.step2_ctx
def test_repo_signatures_have_no_db():
    """抽样检查：3 个核心 repo 方法的 inspect.signature 不包含 db 形参。"""
    from src.repositories.ai_chat_repo import AIChatRepository
    from src.repositories.system_config_repo import SystemConfigRepository
    from src.repositories.embedding_repo import EmbeddingRepository

    sig1 = inspect.signature(AIChatRepository.create_session)
    sig2 = inspect.signature(SystemConfigRepository.upsert)
    sig3 = inspect.signature(EmbeddingRepository.get_by_id)

    for sig in [sig1, sig2, sig3]:
        assert "db" not in sig.parameters, (
            f"方法签名中不应有 db 参数：{sig}"
        )
