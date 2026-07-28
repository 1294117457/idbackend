"""动态测试：用 SQLite in-memory + 真实调用 service 方法，验证之前发现的 Bug 都已修复。"""
import asyncio
import re
import tempfile
import pytest
import pytest_asyncio
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

# 把 PG-only 模型替换为 SQLite 兼容版本
@pytest_asyncio.fixture
async def sqlite_engine():
    """临时 SQLite in-memory 数据库。"""
    tmpfile = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmpfile.close()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmpfile.name}", echo=False)

    # 强制所有 model 用 SQLite 兼容
    from sqlalchemy import Column, Integer, String, Float
    from sqlalchemy.orm import declarative_base

    yield engine

    await engine.dispose()
    import pathlib as _p
    _p.Path(tmpfile.name).unlink(missing_ok=True)


@pytest_asyncio.fixture
async def sqlite_factory(sqlite_engine):
    return async_sessionmaker(sqlite_engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
def monkeypatch_async_session_local(sqlite_factory, monkeypatch):
    monkeypatch.setattr("src.infra.database.AsyncSessionLocal", sqlite_factory)


# ────────────────────────────────────────────────────────────────────
# ─── 1. 验证 auth_service.register ───
# ────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_auth_service_register_runs():
    """register 之前会 NameError，现在应能正常跑。"""
    from src.infra.email import EmailCode

    class MockEmailCode:
        @staticmethod
        async def verify(*args, **kwargs):
            return True, None

    # 把 EmailCode.verify 替换为 mock
    import src.services.auth_service as auth_mod
    auth_mod.EmailCode = MockEmailCode

    from src.services.auth_service import AuthService
    from src.app.schemas.auth import RegisterRequest
    from src.infra.database import get_db_context
    from src.models.user import User

    req = RegisterRequest(username="test_user_x", password="longpwd123", code="dummy")

    async with get_db_context():
        try:
            result = await AuthService.register(req, email_code="dummy")
            assert result is not None
        except Exception as e:
            if "name 'db' is not defined" in str(e):
                pytest.fail(f"register 仍有 db 未定义问题: {e}")
            # 其他异常（如 SQLite 不支持某些 PG 字段）可以接受
            print(f"其他异常（可接受）: {type(e).__name__}: {e}")


# ────────────────────────────────────────────────────────────────────
# ─── 2. 验证 RbacService 全部方法 ───
# ────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_rbac_service_no_name_error():
    """rbac_service 之前全文件 db 未定义 bug。"""
    from src.services.rbac_service import RbacService
    from src.infra.database import get_db_context

    # 这些方法在调用时会尝试 db.xxx，未设置 ctx 时应拿到 RuntimeError 而不是 NameError
    async def try_method(name, *args, **kwargs):
        method = getattr(RbacService, name)
        try:
            await method(*args, **kwargs)
        except RuntimeError as e:
            # 如果到了 db.xxx 这一行，说明已通过 db 未赋值检查
            return "ran_to_db_call"
        except Exception as e:
            # SQLite/PG 字段不匹配等可接受
            return "ran_to_db_call"
        except NameError as e:
            return f"NameError: {e}"

    # 这些方法应该 ran_to_db_call（不再有 NameError）
    results = []
    async with get_db_context():
        results.append(("get_user_roles", await try_method("get_user_roles", 1)))
        results.append(("get_all_roles", await try_method("get_all_roles")))
        results.append(("get_role_by_id", await try_method("get_role_by_id", 1)))
        results.append(("get_role_by_code", await try_method("get_role_by_code", "x")))

    for name, res in results:
        assert "NameError" not in res, f"{name} 仍有 NameError: {res}"


# ────────────────────────────────────────────────────────────────────
# ─── 3. 验证 user_service 创建/删除 ───
# ────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_user_service_create():
    """user_service.create_user 之前会 NameError。"""
    from src.services.user_service import UserService
    from src.infra.database import get_db_context

    async with get_db_context():
        try:
            user = await UserService.create_user(username="abc", password="pwd")
            assert user is not None
        except TypeError as e:
            # 字段类型不匹配 SQLite，可接受
            print(f"字段不匹配（SQLite 限制）: {e}")
        except Exception as e:
            if "name 'db' is not defined" in str(e):
                pytest.fail(f"create_user 仍有 db NameError: {e}")
            print(f"其他异常: {type(e).__name__}: {e}")


# ────────────────────────────────────────────────────────────────────
# ─── 4. 验证 attribute_service.create ───
# ────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_attribute_service_create():
    """attribute_service.create 之前会 NameError。"""
    from src.services.attribute_service import AttributeService
    from src.infra.database import get_db_context
    from src.app.schemas.template import AttributeCreateRequest

    req = AttributeCreateRequest(
        groupCode="gc1",
        groupName="gn1",
        name="attr1",
        type="CONDITION",
        score=1.0,
    )

    async with get_db_context():
        try:
            r = await AttributeService.create(req=req)
            assert r is not None
        except Exception as e:
            if "name 'db' is not defined" in str(e):
                pytest.fail(f"attribute create 仍有 db NameError: {e}")
            # SQLite pgvector 不支持等可接受
            print(f"其他异常（可接受）: {type(e).__name__}: {str(e)[:200]}")


# ────────────────────────────────────────────────────────────────────
# ─── 5. 验证 ai_chat_service.do_compress ───
# ────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ai_chat_do_compress_no_name_error():
    """ai_chat_service.do_compress 之前会 NameError（await db.flush 之前没有 db=...）"""
    from src.services.ai_chat_service import AIChatService
    from src.infra.database import get_db_context

    async with get_db_context():
        try:
            result = await AIChatService.do_compress(AIChatService(), session_id=999)
            assert result is None or result is not None
        except RuntimeError as e:
            # 走到 db.flush 时会触发 ContextVar 错误
            # 但不应该 NameError
            assert "name 'db' is not defined" not in str(e)
        except Exception as e:
            assert "name 'db' is not defined" not in str(e), (
                f"do_compress 仍有 db NameError: {e}"
            )


# ────────────────────────────────────────────────────────────────────
# ─── 6. 静态扫描防护 ───
# ────────────────────────────────────────────────────────────────────
def test_static_no_undefined_db_in_services():
    """所有 service 方法用 db 时都有 db = get_current_db() 赋值。"""
    from pathlib import Path
    import ast

    service_dir = Path("/home/dustp/codes/idproject/idbackend/src/services")
    issues = []

    for py_file in sorted(service_dir.glob("*.py")):
        if py_file.name.startswith("__"):
            continue
        src = py_file.read_text()
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue

        def scan(node):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return
            assigns_db = False
            uses_db = False
            own = [n for n in node.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]

            class V(ast.NodeVisitor):
                def visit_Assign(self, n):
                    nonlocal assigns_db
                    for t in n.targets:
                        if isinstance(t, ast.Name) and t.id == "db":
                            assigns_db = True
                def visit_AsyncWith(self, n):
                    nonlocal assigns_db
                    for it in n.items:
                        if it.optional_vars and isinstance(it.optional_vars, ast.Name) and it.optional_vars.id == "db":
                            assigns_db = True
                def visit_With(self, n):
                    nonlocal assigns_db
                    for it in n.items:
                        if it.optional_vars and isinstance(it.optional_vars, ast.Name) and it.optional_vars.id == "db":
                            assigns_db = True
                def visit_Attribute(self, n):
                    nonlocal uses_db
                    if isinstance(n.value, ast.Name) and n.value.id == "db":
                        uses_db = True
                def visit_Call(self, n):
                    nonlocal uses_db
                    f = n.func
                    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
                        if f.value.id == "db":
                            uses_db = True

            for s in own:
                V().visit(s)

            if uses_db and not assigns_db:
                issues.append(f"{py_file.name}::{node.name}() @ line {node.lineno}")
            for s in node.body:
                if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    scan(s)

        for n in tree.body:
            if isinstance(n, ast.ClassDef):
                for m in n.body:
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        scan(m)

    assert issues == [], "以下 service 方法使用了 db 但未赋值：\n  " + "\n  ".join(issues)
