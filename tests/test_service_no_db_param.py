"""Step 3 测试：验证 service 不再接收 db 形参，从 ContextVar 取 db。

依据：
    docs/docs-backend/dbcontext/step3-service-orchestration.md

运行：
    cd idbackend && pytest tests/test_service_no_db_param.py -v
"""
import asyncio
import inspect
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from src.infra.database import get_db_context, _db_session_var


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
# 测试 1：所有 service 的 async 方法不再有 db 形参
# ════════════════════════════════════════════════════════════════
@pytest.mark.step3_ctx
def test_no_service_method_takes_db_param():
    """所有 service 的 async 方法都不应再有 db: AsyncSession 形参。"""
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
            # 检查第一个形参
            if node.args.args and node.args.args[0].arg == "db":
                first = node.args.args[0]
                if first.annotation and isinstance(first.annotation, ast.Name):
                    if first.annotation.id in ("AsyncSession", "Session"):
                        violations.append(f"{py_file.name}:{node.name}()")

    assert violations == [], (
        f"以下 service 方法仍有 db 形参：\n  " + "\n  ".join(violations)
    )


# ════════════════════════════════════════════════════════════════
# 测试 2：service 源码中不再有 `await db.commit()`
# ════════════════════════════════════════════════════════════════
@pytest.mark.step3_ctx
def test_service_no_await_db_commit():
    """service 源码中不应有 `await db.commit()`（事务由框架管）。"""
    from pathlib import Path

    service_dir = Path("/home/dustp/codes/idproject/idbackend/src/services")
    violations = []

    for py_file in sorted(service_dir.glob("*.py")):
        if py_file.name.startswith("__"):
            continue
        src = py_file.read_text()
        for i, line in enumerate(src.split("\n"), 1):
            if line.strip() == "await db.commit()":
                violations.append(f"{py_file.name}:{i}")

    assert violations == [], (
        f"以下 service 仍有 await db.commit()：\n  " + "\n  ".join(violations)
    )


# ════════════════════════════════════════════════════════════════
# 测试 3：service 源码中不再有 `await db.rollback()`
# ════════════════════════════════════════════════════════════════
@pytest.mark.step3_ctx
def test_service_no_await_db_rollback():
    """service 源码中不应有 `await db.rollback()`（事务由框架管）。"""
    from pathlib import Path

    service_dir = Path("/home/dustp/codes/idproject/idbackend/src/services")
    violations = []

    for py_file in sorted(service_dir.glob("*.py")):
        if py_file.name.startswith("__"):
            continue
        src = py_file.read_text()
        for i, line in enumerate(src.split("\n"), 1):
            if line.strip() == "await db.rollback()":
                violations.append(f"{py_file.name}:{i}")

    assert violations == [], (
        f"以下 service 仍有 await db.rollback()：\n  " + "\n  ".join(violations)
    )


# ════════════════════════════════════════════════════════════════
# 测试 4：service 内部调用 repo 不传 db
# ════════════════════════════════════════════════════════════════
@pytest.mark.step3_ctx
def test_service_repo_calls_no_db():
    """service 内部调用 repo 时不应再传 db 作为第一个位置参数。"""
    from pathlib import Path
    import re

    service_dir = Path("/home/dustp/codes/idproject/idbackend/src/services")
    violations = []

    for py_file in sorted(service_dir.glob("*.py")):
        if py_file.name.startswith("__"):
            continue
        src = py_file.read_text()
        # 形如 AIChatRepository.create_session(db, ...) → 应该有错误
        # 跳过注释和 docstring
        for i, line in enumerate(src.split("\n"), 1):
            # 跳过 docstring 内的内容（简化：跳过含 """ 的行）
            if '"""' in line:
                continue
            if re.search(r'\w+Repository\.\w+\(db,', line):
                violations.append(f"{py_file.name}:{i}: {line.strip()}")
            if re.search(r'\w+Service\.\w+\(db,', line):
                violations.append(f"{py_file.name}:{i}: {line.strip()}")

    assert violations == [], (
        f"以下 service 仍向 repo/service 传 db：\n  " + "\n  ".join(violations)
    )


# ════════════════════════════════════════════════════════════════
# 测试 5：service 模块能 import
# ════════════════════════════════════════════════════════════════
@pytest.mark.step3_ctx
def test_all_services_importable():
    """所有 service 文件都能 import（语法 + 依赖正确）。"""
    services = [
        "ai_chat_service",
        "application_service",
        "attribute_service",
        "auth_service",
        "calculation_service",
        "embedding_service",
        "extra_info_field_service",
        "file_service",
        "rbac_service",
        "rule_service",
        "score_data_service",
        "system_config_service",
        "template_category_service",
        "template_service",
        "user_service",
    ]
    for s in services:
        mod = __import__(f"src.services.{s}", fromlist=[s])
        assert mod is not None, f"无法导入 {s}"


# ════════════════════════════════════════════════════════════════
# 测试 6：service 关键方法签名检查
# ════════════════════════════════════════════════════════════════
@pytest.mark.step3_ctx
def test_service_method_signatures():
    """抽样检查：service 方法签名不含 db 形参。"""
    from src.services.ai_chat_service import AIChatService
    from src.services.application_service import ApplicationService
    from src.services.score_data_service import ScoreDataService

    methods = [
        (AIChatService, "get_or_create_session"),
        (AIChatService, "list_sessions"),
        (AIChatService, "build_context"),
        (ApplicationService, "save_draft"),
        (ApplicationService, "submit"),
        (ScoreDataService, "record"),
        (ScoreDataService, "recalculate"),
    ]

    for cls, method_name in methods:
        sig = inspect.signature(getattr(cls, method_name))
        assert "db" not in sig.parameters, (
            f"{cls.__name__}.{method_name} 仍有 db 形参：{sig}"
        )


# ════════════════════════════════════════════════════════════════
# 测试 7：service 内部不再 import AsyncSession 类型注解
# ════════════════════════════════════════════════════════════════
@pytest.mark.step3_ctx
def test_service_no_asyncsession_type_annotation():
    """service 源码中不应再有 `db: AsyncSession` 形参注解。

    例外：user_service.py 中使用 `async with AsyncSessionLocal()` 自管理 session 是允许的。
    """
    from pathlib import Path
    import re

    service_dir = Path("/home/dustp/codes/idproject/idbackend/src/services")
    violations = []

    for py_file in sorted(service_dir.glob("*.py")):
        if py_file.name.startswith("__"):
            continue
        src = py_file.read_text()
        # 检测 `db: AsyncSession` 作为形参注解
        if re.search(r'db: AsyncSession', src):
            for i, line in enumerate(src.split("\n"), 1):
                if "db: AsyncSession" in line and ":" in line and "AsyncSession" in line.split(":")[1] if ":" in line else False:
                    violations.append(f"{py_file.name}:{i}: {line.strip()}")

    assert violations == [], (
        f"以下 service 仍有 db: AsyncSession 形参：\n  " + "\n  ".join(violations)
    )