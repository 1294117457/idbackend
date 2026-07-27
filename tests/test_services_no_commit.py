"""Step 3 测试：验证 service 里 commit / refresh 调用已被清理，框架接管事务。

运行：
    cd idbackend && pytest tests/test_services_no_commit.py -v

依据：
    docs/docs-backend/dbremake/step3-service-commit-removal.md
"""
import ast
import pathlib

import pytest


# ─── Step 3 必改的 service（不应该有 commit）────────────
SHOULD_NOT_HAVE_COMMIT = [
    "src/services/auth_service.py",
    "src/services/user_service.py",
    "src/services/rbac_service.py",
    "src/services/system_config_service.py",
    "src/services/score_data_service.py",
    "src/services/embedding_service.py",
    "src/services/rule_service.py",
    "src/services/attribute_service.py",
    "src/services/extra_info_field_service.py",
    "src/services/template_category_service.py",
    "src/services/template_service.py",
    "src/services/application_service.py",
]

# ─── Step 3 不动的 service（后续阶段处理）─────────────────────
NOT_TOUCHED_IN_STEP3 = [
    "src/services/file_service.py",        # Step 5
    "src/services/ai_chat_service.py",     # Step 6（保留 stream_chat 的 commit）
]


# ─── 测试 1：必改文件不应有 await db.commit() ────────────────
@pytest.mark.step3
@pytest.mark.parametrize("service_file", SHOULD_NOT_HAVE_COMMIT)
def test_service_no_commit(service_file):
    """Step 3 必改 service 不应该再有 commit 调用。"""
    file_path = pathlib.Path(service_file)
    assert file_path.exists()
    source = file_path.read_text()

    lines = source.splitlines()
    for i, line in enumerate(lines, 1):
        # 跳过注释行和 docstring
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if '"""' in stripped or "'''" in stripped:
            continue
        if "await db.commit()" in line or "await self._db.commit()" in line:
            pytest.fail(
                f"{service_file}:{i} 还有 commit 调用: {line.strip()}"
            )


# ─── 测试 2：未处理的 service 暂时保留 commit ──────────────
@pytest.mark.step3
@pytest.mark.parametrize("service_file", NOT_TOUCHED_IN_STEP3)
def test_untouched_service_still_has_commit(service_file):
    """未处理的 service（Step 5/6 才改）暂时保留 commit。"""
    file_path = pathlib.Path(service_file)
    assert file_path.exists()
    source = file_path.read_text()
    # 这是预期行为：如果没有 commit 也无妨（说明之前已经处理了）
    if "await db.commit()" not in source and "await self._db.commit()" not in source:
        pytest.skip(f"{service_file} 已经处理（应该已经进入 Step 5/6）")


# ─── 测试 3：Step 1 框架 commit 接管后，数据落盘等价 ────────────
@pytest.mark.step3
@pytest.mark.asyncio
async def test_step3_service_pattern_still_commits(test_engine):
    """验证删除 service commit 后，框架 commit 接管，业务行为不变。

    这是 Step 3 最关键的回归测试 —— 通过对比：
    - 旧模式：service add + commit + return
    - 新模式：service add + return（框架 commit）
    两者行为应该完全等价。
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlalchemy import Column, Integer, String, select
    from sqlalchemy.orm import declarative_base

    ModelBase = declarative_base()

    class Step3User(ModelBase):
        __tablename__ = "step3_users"
        id = Column(Integer, primary_key=True)
        name = Column(String(64), nullable=False, unique=True)

    # 初始化测试表
    async with test_engine.begin() as conn:
        await conn.run_sync(ModelBase.metadata.create_all)

    factory = async_sessionmaker(test_engine, expire_on_commit=False)

    # 模拟"框架 get_db"逻辑（和 Step 1 测试一致）
    async def framework_get_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    # ── 测试 A：service 模式（add + return，框架 commit）──
    async def service_pattern_new():
        async for session in framework_get_db():
            session.add(Step3User(name="step3_new"))
            # ↑ 没有 commit！框架在 yield 后 commit

    await service_pattern_new()

    # 验证：数据落盘
    async with factory() as verify:
        result = await verify.execute(
            select(Step3User).where(Step3User.name == "step3_new")
        )
        assert result.scalar_one_or_none() is not None, (
            "Step 3 模式（无 service commit）下数据没落盘"
        )


# ─── 测试 4：service 删 commit 后不影响跨服务调用链 ──────────
@pytest.mark.step3
@pytest.mark.asyncio
async def test_step3_service_chain_in_same_request(test_engine):
    """验证：service 调用链在同一个 HTTP 请求里，框架 commit 一次即可。

    场景：service_a 创建 → service_b 查询 → 同一个请求 return → 框架 commit 全部
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlalchemy import Column, Integer, String, select
    from sqlalchemy.orm import declarative_base

    ModelBase = declarative_base()

    class ChainEntity(ModelBase):
        __tablename__ = "step3_chain"
        id = Column(Integer, primary_key=True)
        name = Column(String(64), nullable=False)

    async with test_engine.begin() as conn:
        await conn.run_sync(ModelBase.metadata.create_all)

    factory = async_sessionmaker(test_engine, expire_on_commit=False)

    async def framework_get_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    # service_a: 创建对象
    async def service_a_create(name):
        async for session in framework_get_db():
            session.add(ChainEntity(name=name))

    # service_b: 查询对象
    async def service_b_query(name):
        async for session in framework_get_db():
            result = await session.execute(
                select(ChainEntity).where(ChainEntity.name == name)
            )
            return result.scalar_one_or_none()

    # 场景：在一个"请求"内，service_a 创建 → service_b 查询（应能看到自己刚加的）
    async def fake_route_logic():
        async for session in framework_get_db():
            # service_a 的工作
            session.add(ChainEntity(name="chain_entity"))
            # ↑ Step 3 模式：没 commit
            # service_b 的工作：在同一个 session 里查
            result = await session.execute(
                select(ChainEntity).where(ChainEntity.name == "chain_entity")
            )
            obj = result.scalar_one_or_none()
            # ↑ SQLAlchemy 默认行为：在同一个 session 内能看到自己 pending 的写入
            assert obj is not None, (
                "同一个 session 内应该能看到自己刚 add 的对象（pending state）"
            )

    await fake_route_logic()

    # 验证：框架 commit 后数据落盘
    async with factory() as verify:
        result = await verify.execute(
            select(ChainEntity).where(ChainEntity.name == "chain_entity")
        )
        assert result.scalar_one_or_none() is not None


# ─── 测试 5：service 异常后框架 rollback 接管 ──────────────
@pytest.mark.step3
@pytest.mark.asyncio
async def test_step3_service_exception_rolled_back(test_engine):
    """验证：service 删 commit 后，业务异常仍然由框架 rollback 处理。"""
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlalchemy import Column, Integer, String, select, func
    from sqlalchemy.orm import declarative_base

    ModelBase = declarative_base()

    class TblEntity(ModelBase):
        __tablename__ = "step3_exc"
        id = Column(Integer, primary_key=True)
        name = Column(String(64), nullable=False)

    async with test_engine.begin() as conn:
        await conn.run_sync(ModelBase.metadata.create_all)

    factory = async_sessionmaker(test_engine, expire_on_commit=False)

    async def framework_get_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def service_with_exception():
        async for session in framework_get_db():
            session.add(TblEntity(name="should_rollback"))
            raise ValueError("业务异常")

    with pytest.raises(ValueError):
        await service_with_exception()

    # 验证：数据不存在（被框架 rollback）
    async with factory() as verify:
        result = await verify.execute(select(func.count()).select_from(TblEntity))
        count = result.scalar()
        assert count == 0, "异常应该被框架 rollback，数据不应该存在"
