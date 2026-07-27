"""Step 6 测试：验证 ai_chat_service.stream_chat 拆短事务。

运行：
    cd idbackend && pytest tests/test_stream_chat_tx.py -v

依据：
    docs/docs-backend/dbremake/step6-stream-chat.md
"""
import asyncio
import inspect
import pathlib
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base


# ─── 最小化测试 model ──────────────────────────────────────
ModelBase = declarative_base()


class TblChatSession(ModelBase):
    """聊天会话（简化版）。"""
    __tablename__ = "step6_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)
    title = Column(String(200), default="新会话")
    last_summary_end_seq = Column(Integer, default=0)
    recent_summary_count = Column(Integer, default=0)
    last_compress_at = Column(DateTime, nullable=True)
    total_summary_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class TblChatMessage(ModelBase):
    """聊天消息。"""
    __tablename__ = "step6_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("step6_sessions.id"), nullable=False)
    role = Column(String(20), nullable=False)
    content = Column(String, nullable=False)
    msg_type = Column(String(20), default="TEXT")
    seq = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


@pytest.fixture
async def step6_engine():
    """共享内存 SQLite。"""
    import tempfile
    tmpfile = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmpfile.close()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmpfile.name}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(ModelBase.metadata.create_all)
    yield engine
    await engine.dispose()
    import pathlib as _p
    _p.Path(tmpfile.name).unlink(missing_ok=True)


@pytest.fixture
async def step6_factory(step6_engine):
    return async_sessionmaker(step6_engine, expire_on_commit=False)


# ════════════════════════════════════════════════════════════════
# 测试 1：get_db_context 函数存在且是 asynccontextmanager
# ════════════════════════════════════════════════════════════════
@pytest.mark.step6
def test_get_db_context_exists():
    """Step 6 新增的 get_db_context 必须存在。"""
    from src.infra.database import get_db_context
    assert get_db_context is not None
    # @asynccontextmanager 装饰后，调用 get_db_context() 才返回 AsyncContextManager
    ctx = get_db_context()
    assert hasattr(ctx, "__aenter__"), (
        "get_db_context() 应该是 async context manager"
    )
    assert hasattr(ctx, "__aexit__")
    # 不实际进入 context（避免连接 PG）
    # ↑ 这里只验证接口存在，连接错误留到实际跑测试时


# ════════════════════════════════════════════════════════════════
# 测试 2：get_db_context 业务正常 → commit（用测试 engine）
# ════════════════════════════════════════════════════════════════
@pytest.mark.step6
@pytest.mark.asyncio
async def test_get_db_context_commits_on_success(step6_factory):
    """get_db_context 业务正常 → 自动 commit。"""
    # 用测试 factory 替换项目里的 AsyncSessionLocal
    import src.infra.database as db_module
    original = db_module.AsyncSessionLocal
    db_module.AsyncSessionLocal = lambda: step6_factory()

    try:
        from src.infra.database import get_db_context
        async with get_db_context() as db:
            session = TblChatSession(user_id=1, title="test")
            db.add(session)
            await db.flush()
            captured_id = session.id

        async with step6_factory() as verify:
            result = await verify.execute(
                select(TblChatSession).where(TblChatSession.id == captured_id)
            )
            obj = result.scalar_one_or_none()
            assert obj is not None, "get_db_context 应该 commit 数据"
    finally:
        db_module.AsyncSessionLocal = original


# ════════════════════════════════════════════════════════════════
# 测试 3：get_db_context 异常 → rollback
# ════════════════════════════════════════════════════════════════
@pytest.mark.step6
@pytest.mark.asyncio
async def test_get_db_context_rolls_back_on_exception(step6_factory):
    """get_db_context 业务异常 → 自动 rollback。"""
    import src.infra.database as db_module
    original = db_module.AsyncSessionLocal
    db_module.AsyncSessionLocal = lambda: step6_factory()

    try:
        from src.infra.database import get_db_context
        with pytest.raises(ValueError, match="test"):
            async with get_db_context() as db:
                session = TblChatSession(user_id=1, title="will_rollback")
                db.add(session)
                await db.flush()
                raise ValueError("test")

        async with step6_factory() as verify:
            result = await verify.execute(select(TblChatSession))
            sessions = result.scalars().all()
            assert len(sessions) == 0, "异常应该被 rollback"
    finally:
        db_module.AsyncSessionLocal = original


# ════════════════════════════════════════════════════════════════
# 测试 4：stream_chat 函数没有手动 commit（除 import 语句外）
# ════════════════════════════════════════════════════════════════
@pytest.mark.step6
def test_stream_chat_no_manual_commit():
    """stream_chat 函数体内不应该再有 commit/rollback/refresh 调用。"""
    src = pathlib.Path("src/services/ai_chat_service.py").read_text()
    # 找 stream_chat 函数体
    import re
    match = re.search(
        r"async def stream_chat\(self,.*?\n(?P<body>.*?)(?=\n    async def|\n    def|\nclass |\Z)",
        src,
        re.DOTALL,
    )
    if match:
        body = match.group("body")
        # 检查
        for forbidden in ["await db.commit(", "await db.rollback(", "await db.refresh("]:
            assert forbidden not in body, (
                f"stream_chat 函数体还有: {forbidden}"
            )


# ════════════════════════════════════════════════════════════════
# 测试 5：stream_chat 用 get_db_context 拆短事务
# ════════════════════════════════════════════════════════════════
@pytest.mark.step6
def test_stream_chat_uses_get_db_context():
    """stream_chat 应该用 get_db_context 拆短事务。"""
    src = pathlib.Path("src/services/ai_chat_service.py").read_text()
    assert "get_db_context" in src, "stream_chat 应该 import get_db_context"
    # 至少 2 次（事务 1 + 事务 2）
    count = src.count("async with get_db_context()")
    assert count >= 2, f"应该至少有 2 个 async with get_db_context()（拆短事务），但实际有 {count}"


# ════════════════════════════════════════════════════════════════
# 测试 6：模拟 stream_chat 完整流程（事务 1 + LLM + 事务 2）
# ════════════════════════════════════════════════════════════════
@pytest.mark.step6
@pytest.mark.asyncio
async def test_simulated_stream_chat_full_flow(step6_factory):
    """模拟 stream_chat 的完整流程：事务 1 准备 → LLM → 事务 2 完成。"""
    import src.infra.database as db_module
    original = db_module.AsyncSessionLocal
    db_module.AsyncSessionLocal = lambda: step6_factory()

    try:
        from src.infra.database import get_db_context

        # 模拟 LLM 流式响应
        async def fake_llm_stream(messages):
            for chunk_text in ["你好", "，", "世界"]:
                chunk = MagicMock()
                chunk.content = chunk_text
                yield chunk

        # ── 事务 1：准备 ──
        async with get_db_context() as db:
            session = TblChatSession(user_id=1, title="new")
            db.add(session)
            await db.flush()
            session_id = session.id

            user_msg = TblChatMessage(
                session_id=session_id,
                role="user",
                content="hi",
            )
            db.add(user_msg)
            await db.flush()

        # ↑ 事务 1 commit

        # ── LLM 调用（不在事务内）──
        full_content = ""
        async for chunk in fake_llm_stream([]):
            full_content += chunk.content

        # ── 事务 2：保存 assistant message ──
        async with get_db_context() as db:
            assistant_msg = TblChatMessage(
                session_id=session_id,
                role="assistant",
                content=full_content,
            )
            db.add(assistant_msg)
            await db.flush()

        # ↑ 事务 2 commit

        async with step6_factory() as verify:
            result = await verify.execute(
                select(TblChatMessage).order_by(TblChatMessage.id)
            )
            messages = result.scalars().all()
            assert len(messages) == 2
            assert messages[0].role == "user"
            assert messages[1].role == "assistant"
            assert messages[1].content == "你好，世界"
    finally:
        db_module.AsyncSessionLocal = original


# ════════════════════════════════════════════════════════════════
# 测试 7：事务 1 commit 后，LLM 期间另一个请求能正常用连接
# ════════════════════════════════════════════════════════════════
@pytest.mark.step6
@pytest.mark.asyncio
async def test_concurrent_request_during_llm(step6_factory):
    """模拟 stream_chat 期间，事务 1 已 commit，LLM 期间其他请求能用 DB。"""
    import src.infra.database as db_module
    original = db_module.AsyncSessionLocal
    db_module.AsyncSessionLocal = lambda: step6_factory()

    try:
        from src.infra.database import get_db_context
        import asyncio

        # 准备阶段：事务 1 commit
        async with get_db_context() as db:
            session = TblChatSession(user_id=1, title="step6_test")
            db.add(session)
            await db.flush()

        # LLM 期间：另一个请求并发执行 DB 操作
        async def other_request():
            async with get_db_context() as db:
                result = await db.execute(select(TblChatSession))
                return result.scalars().all()

        # 模拟慢 LLM
        async def slow_llm():
            await asyncio.sleep(0.1)
            yield MagicMock(content="done")

        other_task = asyncio.create_task(other_request())

        async for _ in slow_llm():
            pass

        sessions = await other_task
        assert len(sessions) >= 1, "LLM 期间其他请求应该能正常用 DB"
    finally:
        db_module.AsyncSessionLocal = original


# ════════════════════════════════════════════════════════════════
# 测试 8：LLM 调用失败时事务状态
# ════════════════════════════════════════════════════════════════
@pytest.mark.step6
@pytest.mark.asyncio
async def test_stream_chat_llm_failure_state(step6_factory):
    """模拟 LLM 失败：事务 1 已 commit（user_msg 在），事务 2 不开始。"""
    import src.infra.database as db_module
    original = db_module.AsyncSessionLocal
    db_module.AsyncSessionLocal = lambda: step6_factory()

    try:
        from src.infra.database import get_db_context

        user_msg_id = None
        session_id = None
        async with get_db_context() as db:
            session = TblChatSession(user_id=1, title="llm_fail_test")
            db.add(session)
            await db.flush()
            session_id = session.id

            user_msg = TblChatMessage(
                session_id=session_id,
                role="user",
                content="hi",
            )
            db.add(user_msg)
            await db.flush()
            user_msg_id = user_msg.id

        # LLM 失败（模拟）
        class LLMMock:
            def astream(self, messages):
                async def gen():
                    raise ConnectionError("LLM 调用失败")
                    yield
                return gen()

        llm = LLMMock()
        error_event = None
        try:
            async for chunk in llm.astream([]):
                pass
        except ConnectionError as e:
            error_event = {"event": "error", "message": str(e)}

        assert error_event is not None

        async with step6_factory() as verify:
            result = await verify.execute(select(TblChatMessage))
            messages = result.scalars().all()
            assert len(messages) == 1, "只有 user_msg"
            assert messages[0].id == user_msg_id
    finally:
        db_module.AsyncSessionLocal = original
