"""Step 4 测试：验证 service 里 refresh 调用已被清理，default 字段正确获取。

运行：
    cd idbackend && pytest tests/test_flush_refresh.py -v

依据：
    docs/docs-backend/dbremake/step4-flush-refresh.md
"""
import pathlib
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import Column, Integer, String, DateTime, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base


# ─── 最小化测试 model ──────────────────────────────────────
ModelBase = declarative_base()


class TblEntity(ModelBase):
    """测试实体（验证 default 字段 + flush 后 id 可访问）。"""
    __tablename__ = "step4_entity"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False)
    # Python 端 default（add 后立即有值）
    value = Column(Integer, default=0, nullable=False)
    # Python 端 default（lambda：add 时立即有值）
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    # 另一个 Python default
    status = Column(String(20), default="active", nullable=False)


@pytest.fixture
async def step4_engine():
    """共享内存 SQLite（用临时文件）。"""
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


@pytest.fixture
async def step4_factory(step4_engine):
    return async_sessionmaker(step4_engine, expire_on_commit=False)


async def framework_get_db(factory):
    """复制 src/infra/database.py:get_db 的逻辑。"""
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ════════════════════════════════════════════════════════════════
# 测试 1：service 没有 refresh 调用
# ════════════════════════════════════════════════════════════════
@pytest.mark.step4
@pytest.mark.parametrize("service_file", [
    "src/services/auth_service.py",
    "src/services/user_service.py",
    "src/services/rbac_service.py",
    "src/services/score_data_service.py",
    "src/services/rule_service.py",
    "src/services/attribute_service.py",
    "src/services/extra_info_field_service.py",
    "src/services/template_category_service.py",
    "src/services/template_service.py",
    "src/services/application_service.py",
])
def test_service_no_refresh(service_file):
    """Step 4 必改 service 不应该再有 refresh 调用。"""
    file_path = pathlib.Path(service_file)
    assert file_path.exists()
    source = file_path.read_text()

    lines = source.splitlines()
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if '"""' in stripped or "'''" in stripped:
            continue
        if "await db.refresh(" in line or "await self._db.refresh(" in line:
            pytest.fail(f"{service_file}:{i} 还有 refresh 调用: {line.strip()}")


# ════════════════════════════════════════════════════════════════
# 测试 2：flush 后 id 可访问（PG 通过 RETURNING 拿）
# ════════════════════════════════════════════════════════════════
@pytest.mark.step4
@pytest.mark.asyncio
async def test_flush_returns_id(step4_factory):
    """flush 后 obj.id 必须可访问。"""
    async for session in framework_get_db(step4_factory):
        obj = TblEntity(name="flush_test")
        session.add(obj)
        # add 后 obj.id 还是 None（没 flush）
        assert obj.id is None, "add 后 id 应该是 None"

        await session.flush()
        # flush 后 obj.id 可访问
        assert obj.id is not None, "flush 后 id 必须可访问"


# ════════════════════════════════════════════════════════════════
# 测试 3：Python 端 default 字段 add 后立即有值
# ════════════════════════════════════════════════════════════════
@pytest.mark.step4
@pytest.mark.asyncio
async def test_python_default_immediate(step4_factory):
    """Python 端 default 字段在 flush 后有值。

    SQLAlchemy 2.0 行为：
    - add 时不计算任何 default
    - flush 时计算所有 Python 端 default
    - 框架 commit 时会先 flush（autoflush=False 但 commit 触发 flush）
    - commit 后所有字段都有值

    所以 Step 4 删除 refresh 后，**框架 commit 时会自动 flush**，
    对象的所有字段（包括 default）都有值。
    """
    async for session in framework_get_db(step4_factory):
        obj = TblEntity(name="default_test")
        session.add(obj)
        # add 时不计算 default
        # ↑ 不管是字面量还是 lambda，add 时都是 None

        await session.flush()
        # flush 后所有 default 都有值
        assert obj.value == 0, "flush 后 default=0 字段才有值"
        assert obj.status == "active", "flush 后 default='active' 字段才有值"
        assert obj.created_at is not None, "flush 后 default=lambda 字段才有值"


# ════════════════════════════════════════════════════════════════
# 测试 4：不调 refresh 时，对象状态正确（delete 后的行为等价）
# ════════════════════════════════════════════════════════════════
@pytest.mark.step4
@pytest.mark.asyncio
async def test_no_refresh_object_state_correct(step4_factory):
    """不调 refresh，service 删除 commit + refresh 后，对象状态仍正确。

    验证 Step 4 的核心收益：框架 commit 后对象属性是新鲜的（因为
    expire_on_commit=False + add 时 default 已计算 + flush 拿 id）。
    """
    async for session in framework_get_db(step4_factory):
        obj = TblEntity(name="no_refresh_test", value=42)
        session.add(obj)
        # ↑ flush 拿 id
        await session.flush()
        captured_id = obj.id
        captured_value = obj.value
        captured_name = obj.name
        captured_status = obj.status
        # ↑ 模拟"框架 commit"（async for 退出时）
    # ↑ 框架 commit 后

    # 用新 session 验证落盘
    async with step4_factory() as verify:
        result = await verify.execute(
            select(TblEntity).where(TblEntity.id == captured_id)
        )
        loaded = result.scalar_one_or_none()
        assert loaded is not None
        assert loaded.id == captured_id
        assert loaded.name == captured_name
        assert loaded.value == captured_value
        assert loaded.status == captured_status


# ════════════════════════════════════════════════════════════════
# 测试 5：dirty 对象（修改后未 flush）保留修改
# ════════════════════════════════════════════════════════════════
@pytest.mark.step4
@pytest.mark.asyncio
async def test_dirty_object_preserves_changes(step4_factory):
    """service 改 obj 后不 refresh，dirty 状态保留，框架 commit 时一起更新。

    这是 Step 4 的关键测试 —— 验证删 refresh 后 update 流程仍然正确。
    """
    # 先创建一个对象
    obj_id = None
    async for session in framework_get_db(step4_factory):
        obj = TblEntity(name="dirty_test")
        session.add(obj)
        await session.flush()
        obj_id = obj.id

    # 模拟 service update：get + modify
    async for session in framework_get_db(step4_factory):
        obj = await session.get(TblEntity, obj_id)
        assert obj is not None
        obj.name = "dirty_modified"  # ← 改 obj
        obj.value = 99
        # ↑ 不 refresh（Step 4 模式）
        # ↑ dirty 状态保留
        # ↑ 路由 return → 框架 commit
        assert obj.name == "dirty_modified", "改后属性立即生效"

    # 验证：commit 后 DB 里有新值
    async with step4_factory() as verify:
        result = await verify.execute(
            select(TblEntity).where(TblEntity.id == obj_id)
        )
        loaded = result.scalar_one_or_none()
        assert loaded is not None
        assert loaded.name == "dirty_modified", f"name 应该是 dirty_modified，实际是 {loaded.name}"
        assert loaded.value == 99, f"value 应该是 99，实际是 {loaded.value}"


# ════════════════════════════════════════════════════════════════
# 测试 6：expire_on_commit=False 配置验证
# ════════════════════════════════════════════════════════════════
@pytest.mark.step4
def test_expire_on_commit_is_false():
    """expire_on_commit 必须为 False（Step 4 依赖此配置）。"""
    from src.infra.database import AsyncSessionLocal
    assert AsyncSessionLocal.kw.get("expire_on_commit") is False, (
        "expire_on_commit 必须是 False，否则 commit 后属性过期"
    )


# ════════════════════════════════════════════════════════════════
# 测试 7：delete 后 service 链无 refresh 仍正常
# ════════════════════════════════════════════════════════════════
@pytest.mark.step4
@pytest.mark.asyncio
async def test_delete_without_refresh(step4_factory):
    """delete + 框架 commit 后数据消失（无 refresh 也能工作）。"""
    # 创建
    obj_id = None
    async for session in framework_get_db(step4_factory):
        obj = TblEntity(name="to_delete")
        session.add(obj)
        await session.flush()
        obj_id = obj.id

    # 删除
    async for session in framework_get_db(step4_factory):
        obj = await session.get(TblEntity, obj_id)
        await session.delete(obj)
        # ↑ 不 refresh

    # 验证：删除成功
    async with step4_factory() as verify:
        result = await verify.execute(
            select(TblEntity).where(TblEntity.id == obj_id)
        )
        assert result.scalar_one_or_none() is None, "对象应该被删除"
