"""Step 5 测试：验证 file_service 不再有 commit/rollback/refresh，框架接管事务。

运行：
    cd idbackend && pytest tests/test_file_service_compensation.py -v

依据：
    docs/docs-backend/dbremake/step5-file-service.md
"""
import pathlib
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import Column, Integer, String, Boolean, DateTime, select, func
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base


# ─── 最小化测试 model ──────────────────────────────────────
ModelBase = declarative_base()


class TblFile(ModelBase):
    """测试文件元数据表（模拟 file_service 用到的字段）。"""
    __tablename__ = "step5_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    object_name = Column(String(255), nullable=False, unique=True)
    original_name = Column(String(255), nullable=False)
    content_type = Column(String(100), nullable=False)
    file_size = Column(Integer, default=0)
    file_category = Column(String(50), nullable=False, default="DOCUMENT")
    is_deleted = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False)


@pytest.fixture
async def step5_engine():
    """共享内存 SQLite（用 file:memdb1?mode=memory&cache=shared&uri=true）。"""
    import tempfile
    # 用临时文件代替 in-memory，避免连接隔离问题
    tmpfile = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmpfile.close()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmpfile.name}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(ModelBase.metadata.create_all)
    yield engine
    await engine.dispose()
    pathlib.Path(tmpfile.name).unlink(missing_ok=True)


@pytest.fixture
async def step5_factory(step5_engine):
    return async_sessionmaker(step5_engine, expire_on_commit=False)


async def framework_get_db(factory):
    """复制 src/infra/database.py:get_db 逻辑。"""
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ════════════════════════════════════════════════════════════════
# 测试 1：file_service 没有 commit / rollback / refresh
# ════════════════════════════════════════════════════════════════
@pytest.mark.step5
def test_file_service_no_db_commit():
    """file_service 不应该有 commit / rollback / refresh 调用。"""
    source = pathlib.Path("src/services/file_service.py").read_text()

    forbidden = [
        "await self._db.commit()",
        "await self._db.rollback()",
        "await self._db.refresh(",
    ]
    for f in forbidden:
        assert f not in source, f"file_service 仍然有: {f}"


# ════════════════════════════════════════════════════════════════
# 测试 2：上传成功：DB 和 MinIO 都有对象（用 mock storage 模拟）
# ════════════════════════════════════════════════════════════════
@pytest.mark.step5
@pytest.mark.asyncio
async def test_upload_success_data_persisted(step5_factory):
    """上传成功：add + return → 框架 commit → DB 里有对象。"""
    from datetime import datetime
    async for session in framework_get_db(step5_factory):
        meta = TblFile(
            object_name="doc/test.pdf",
            original_name="test.pdf",
            content_type="application/pdf",
            file_size=1024,
            created_at=datetime.now(),
        )
        session.add(meta)
        await session.flush()
        captured_id = meta.id

    # 验证：DB 里有对象
    async with step5_factory() as verify:
        result = await verify.execute(
            select(TblFile).where(TblFile.id == captured_id)
        )
        loaded = result.scalar_one_or_none()
        assert loaded is not None
        assert loaded.object_name == "doc/test.pdf"


# ════════════════════════════════════════════════════════════════
# 测试 3：upload_avatar 旧头像 mark_deleted 在同一事务
# ════════════════════════════════════════════════════════════════
@pytest.mark.step5
@pytest.mark.asyncio
async def test_upload_avatar_old_marked_deleted(step5_factory):
    """upload_avatar 改造后：旧头像在同一事务被 mark_deleted。"""
    from datetime import datetime

    # 先创建一个旧头像
    old_id = None
    async for session in framework_get_db(step5_factory):
        old = TblFile(
            object_name="avatar/old.png",
            original_name="old.png",
            content_type="image/png",
            file_category="AVATAR",
            created_at=datetime.now(),
        )
        session.add(old)
        await session.flush()
        old_id = old.id

    # 模拟 upload_avatar 流程：在同一个事务里 add 新 + mark old deleted
    new_id = None
    async for session in framework_get_db(step5_factory):
        new = TblFile(
            object_name="avatar/new.png",
            original_name="new.png",
            content_type="image/png",
            file_category="AVATAR",
            created_at=datetime.now(),
        )
        session.add(new)
        await session.flush()
        new_id = new.id

        # 同一个 session 找旧头像并 mark_deleted
        old = await session.get(TblFile, old_id)
        old.mark_deleted() if hasattr(old, "mark_deleted") else setattr(old, "is_deleted", True)

    # 验证：新旧头像的状态
    async with step5_factory() as verify:
        new_meta = await verify.get(TblFile, new_id)
        old_meta = await verify.get(TblFile, old_id)
        assert new_meta is not None, "新头像应该落盘"
        assert old_meta.is_deleted is True, "旧头像应该被 mark_deleted"


# ════════════════════════════════════════════════════════════════
# 测试 4：update_file 改动 dirty 状态被框架 commit
# ════════════════════════════════════════════════════════════════
@pytest.mark.step5
@pytest.mark.asyncio
async def test_update_dirty_object_committed_by_framework(step5_factory):
    """update_file 改造后：改动 obj + return → 框架 commit。"""
    from datetime import datetime

    # 创建
    file_id = None
    async for session in framework_get_db(step5_factory):
        meta = TblFile(
            object_name="doc/test.pdf",
            original_name="test.pdf",
            content_type="application/pdf",
            file_size=1024,
            created_at=datetime.now(),
        )
        session.add(meta)
        await session.flush()
        file_id = meta.id

    # 模拟 update_file：get + 改 + return（无 commit / refresh）
    async for session in framework_get_db(step5_factory):
        meta = await session.get(TblFile, file_id)
        meta.original_name = "modified.pdf"  # ← dirty
        meta.file_size = 2048

    # 验证：DB 里有新值
    async with step5_factory() as verify:
        loaded = await verify.get(TblFile, file_id)
        assert loaded.original_name == "modified.pdf"
        assert loaded.file_size == 2048


# ════════════════════════════════════════════════════════════════
# 测试 5：delete_file mark_deleted 后框架 commit
# ════════════════════════════════════════════════════════════════
@pytest.mark.step5
@pytest.mark.asyncio
async def test_delete_marks_deleted_by_framework(step5_factory):
    """delete_file 改造后：mark_deleted + return → 框架 commit。"""
    from datetime import datetime

    # 创建
    file_id = None
    async for session in framework_get_db(step5_factory):
        meta = TblFile(
            object_name="doc/delete.pdf",
            original_name="delete.pdf",
            content_type="application/pdf",
            created_at=datetime.now(),
        )
        session.add(meta)
        await session.flush()
        file_id = meta.id

    # 模拟 delete_file
    async for session in framework_get_db(step5_factory):
        meta = await session.get(TblFile, file_id)
        setattr(meta, "is_deleted", True)

    # 验证：is_deleted=True
    async with step5_factory() as verify:
        loaded = await verify.get(TblFile, file_id)
        assert loaded.is_deleted is True


# ════════════════════════════════════════════════════════════════
# 测试 6：异常路径框架 rollback 仍然有效
# ════════════════════════════════════════════════════════════════
@pytest.mark.step5
@pytest.mark.asyncio
async def test_upload_exception_rolled_back(step5_factory):
    """上传失败时框架 rollback → DB 里没对象。"""
    from datetime import datetime
    try:
        async for session in framework_get_db(step5_factory):
            meta = TblFile(
                object_name="doc/fail.pdf",
                original_name="fail.pdf",
                content_type="application/pdf",
                created_at=datetime.now(),
            )
            session.add(meta)
            await session.flush()
            raise ValueError("MinIO 上传失败模拟")
    except ValueError:
        pass

    # 验证：DB 里没对象
    async with step5_factory() as verify:
        result = await verify.execute(select(func.count()).select_from(TblFile))
        count = result.scalar()
        assert count == 0, "异常应该被框架 rollback"


# ════════════════════════════════════════════════════════════════
# 测试 7：file_service 整体仍可导入
# ════════════════════════════════════════════════════════════════
@pytest.mark.step5
def test_file_service_importable():
    """改造后 file_service 能正常导入。"""
    from src.services.file_service import FileService
    assert hasattr(FileService, "upload_file")
    assert hasattr(FileService, "upload_avatar")
    assert hasattr(FileService, "update_file")
    assert hasattr(FileService, "delete_file")
