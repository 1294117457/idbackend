"""Step 4 测试：验证 route 函数不再接收 db 形参，用 _db 触发 ContextVar。

依据：
    docs/docs-backend/dbcontext/step4-route-pure.md

运行：
    cd idbackend && pytest tests/test_route_no_db_param.py -v
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
# 测试 1：route 函数不再有 db 形参（应有 _db 形参）
# ════════════════════════════════════════════════════════════════
@pytest.mark.step4_ctx
def test_route_no_db_param():
    """route 函数不应再有 db 形参；应使用 _db 触发 ContextVar。"""
    from pathlib import Path
    import re

    route_dir = Path("/home/dustp/codes/idproject/idbackend/src/app/routes")
    violations = []

    for py_file in sorted(route_dir.glob("*.py")):
        if py_file.name.startswith("__"):
            continue
        src = py_file.read_text()
        # 查找路由函数定义中的 db 形参（带 Depends）
        # 形参 `db: AsyncSession = Depends(get_db)`
        if re.search(r'\bdb: AsyncSession\s*=\s*Depends\(get_db\)', src):
            violations.append(f"{py_file.name}: 仍有 'db: AsyncSession = Depends(get_db)' 形参")

    assert violations == [], (
        f"以下 route 仍有 db 形参：\n  " + "\n  ".join(violations)
    )


# ════════════════════════════════════════════════════════════════
# 测试 2：route 源码中存在 _db 形参（触发 ContextVar）
# ════════════════════════════════════════════════════════════════
@pytest.mark.step4_ctx
def test_route_has_dummy_db():
    """至少 1 个 route 应使用 _db 形参（说明框架事务边界已就位）。"""
    from pathlib import Path
    import re

    route_dir = Path("/home/dustp/codes/idproject/idbackend/src/app/routes")
    found = 0

    for py_file in sorted(route_dir.glob("*.py")):
        if py_file.name.startswith("__"):
            continue
        src = py_file.read_text()
        if re.search(r'_db: AsyncSession\s*=\s*Depends\(get_db\)', src):
            found += 1

    assert found > 0, "没有 route 使用 _db 触发 ContextVar（应至少 1 个）"


# ════════════════════════════════════════════════════════════════
# 测试 3：route 函数能 import
# ════════════════════════════════════════════════════════════════
@pytest.mark.step4_ctx
def test_routes_importable():
    """所有 route 文件都能 import（语法 + 依赖正确）。"""
    routes = [
        "ai_chat", "application", "attribute", "auth", "embedding",
        "extra_info_field", "file", "health", "permission", "proof",
        "role", "rule", "score_data", "system_config", "template",
        "template_category", "user",
    ]
    for r in routes:
        mod = __import__(f"src.app.routes.{r}", fromlist=[r])
        assert mod is not None, f"无法导入 {r}"


# ════════════════════════════════════════════════════════════════
# 测试 4：route 内部不再直接传 db 给 service / repo
# ════════════════════════════════════════════════════════════════
@pytest.mark.step4_ctx
def test_route_no_db_passed():
    """route 内部调用 service / repo 时不应传 db 形参。"""
    from pathlib import Path
    import re

    route_dir = Path("/home/dustp/codes/idproject/idbackend/src/app/routes")
    violations = []

    for py_file in sorted(route_dir.glob("*.py")):
        if py_file.name.startswith("__"):
            continue
        src = py_file.read_text()
        for i, line in enumerate(src.split("\n"), 1):
            # 跳过注释
            if '"""' in line or line.strip().startswith("#"):
                continue
            if re.search(r'\w+\.\w+\(db,', line):
                violations.append(f"{py_file.name}:{i}: {line.strip()}")

    assert violations == [], (
        f"以下 route 仍传 db 给 service/repo：\n  " + "\n  ".join(violations)
    )


# ════════════════════════════════════════════════════════════════
# 测试 5：FastAPI Depends + get_db 仍能触发 ContextVar（端到端）
# ════════════════════════════════════════════════════════════════
@pytest.mark.step4_ctx
@pytest.mark.asyncio
async def test_depends_get_db_sets_contextvar():
    """验证 FastAPI Depends(get_db) 设置 ContextVar。"""
    from src.infra.database import get_db

    # 模拟 FastAPI Depends 调用
    gen = get_db()
    await gen.__anext__()  # 进入
    assert _db_session_var.get() is not None, "Depends(get_db) 必须设置 ContextVar"

    # 退出
    try:
        await gen.__anext__()
    except StopAsyncIteration:
        pass
    assert _db_session_var.get() is None, "Depends(get_db) 退出必须 reset ContextVar"


# ════════════════════════════════════════════════════════════════
# 测试 6：route 函数签名检查（抽样）
# ════════════════════════════════════════════════════════════════
@pytest.mark.step4_ctx
def test_route_signatures_have_no_db():
    """抽样检查：route 函数签名不含 db 形参。"""
    import re
    from pathlib import Path

    route_dir = Path("/home/dustp/codes/idproject/idbackend/src/app/routes")
    found_with_db = 0
    found_with_dummy_db = 0

    for py_file in sorted(route_dir.glob("*.py")):
        if py_file.name.startswith("__"):
            continue
        src = py_file.read_text()
        # 统计 db 形参数量
        found_with_db += len(re.findall(r'\bdb: AsyncSession\s*=\s*Depends\(get_db\)', src))
        # 统计 _db 形参数量
        found_with_dummy_db += len(re.findall(r'_db: AsyncSession\s*=\s*Depends\(get_db\)', src))

    assert found_with_db == 0, f"应没有 db 形参，但找到 {found_with_db} 个"
    assert found_with_dummy_db > 0, f"应至少 1 个 _db 形参，但找到 {found_with_dummy_db} 个"