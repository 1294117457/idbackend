"""Step 3 会话压缩 - 表结构迁移

对应文档: docs/step2/agent/06-context-compress.md §10.1

变更:
  agent_session_snapshots:
    - DROP message_count / last_message_at / needs_compress / total_message_count
    - ADD  last_summary_end_seq / recent_summary_count / last_summary_at / total_summary_count
  agent_session_summaries:
    - ADD is_archived BOOLEAN NOT NULL DEFAULT FALSE
  NEW INDEX idx_agent_session_summaries_archived (session_id, is_archived, end_seq)

幂等: 全部使用 IF EXISTS / IF NOT EXISTS, 可重复跑
"""
import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.infra.config import get_async_database_url as get_database_url


ALTER_SQLS = [
    # ───── 1. 删除旧字段 ─────
    "ALTER TABLE agent_session_snapshots DROP COLUMN IF EXISTS message_count;",
    "ALTER TABLE agent_session_snapshots DROP COLUMN IF EXISTS last_message_at;",
    "ALTER TABLE agent_session_snapshots DROP COLUMN IF EXISTS needs_compress;",
    "ALTER TABLE agent_session_snapshots DROP COLUMN IF EXISTS total_message_count;",

    # ───── 2. 新增字段到 snapshot ─────
    """
    ALTER TABLE agent_session_snapshots
    ADD COLUMN IF NOT EXISTS last_summary_end_seq INTEGER NOT NULL DEFAULT 0;
    """,
    """
    ALTER TABLE agent_session_snapshots
    ADD COLUMN IF NOT EXISTS recent_summary_count INTEGER NOT NULL DEFAULT 0;
    """,
    """
    ALTER TABLE agent_session_snapshots
    ADD COLUMN IF NOT EXISTS last_summary_at TIMESTAMP WITH TIME ZONE;
    """,
    """
    ALTER TABLE agent_session_snapshots
    ADD COLUMN IF NOT EXISTS total_summary_count INTEGER NOT NULL DEFAULT 0;
    """,

    # ───── 3. summary 表新增 is_archived ─────
    """
    ALTER TABLE agent_session_summaries
    ADD COLUMN IF NOT EXISTS is_archived BOOLEAN NOT NULL DEFAULT FALSE;
    """,

    # ───── 4. 新增索引 ─────
    """
    CREATE INDEX IF NOT EXISTS idx_agent_session_summaries_archived
    ON agent_session_summaries (session_id, is_archived, end_seq);
    """,
]


async def main():
    engine = create_async_engine(get_database_url(), echo=False)

    async with engine.begin() as conn:
        for sql in ALTER_SQLS:
            short = " ".join(sql.split())[:80]
            try:
                await conn.execute(text(sql))
                print(f"[OK]   {short}")
            except Exception as e:
                msg = str(e).lower()
                if "already exists" in msg or "does not exist" in msg:
                    # DROP COLUMN IF EXISTS 本身已容错, 这里只是兜底
                    print(f"[SKIP] {short}")
                else:
                    print(f"[ERROR] {e}")
                    raise

    await engine.dispose()
    print("\n[done] step3 compress schema migrated")


if __name__ == "__main__":
    asyncio.run(main())
