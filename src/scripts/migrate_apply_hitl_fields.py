"""ApplyNode HITL 数据库迁移

新增字段：
- agent_messages.status: 消息状态（normal / apply_pending）
- agent_messages.pending_data: HITL 待确认数据（JSONB）

用法:
    python -m src.scripts.migrate_apply_hitl_fields

幂等设计：已存在的字段/索引会跳过，不会报错。
"""
import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.infra.config import get_async_database_url


async def main():
    engine = create_async_engine(get_async_database_url(), echo=False)

    # 注意：PostgreSQL ADD COLUMN 在列已存在时会报 duplicate column 错误，
    # 因此用 TRY...EXCEPTION 包装，错误时静默跳过。
    sqls = [
        # 1. 新建类型（如果不存在）
        """
        DO $$
        BEGIN
            CREATE TYPE messagestatus AS ENUM ('normal', 'apply_pending');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
        """,

        # 2. 添加 status 字段（幂等）
        """
        DO $$
        BEGIN
            ALTER TABLE agent_messages ADD COLUMN status messagestatus NOT NULL DEFAULT 'normal';
        EXCEPTION
            WHEN duplicate_column THEN null;
        END $$;
        """,

        # 3. 添加 pending_data 字段（幂等）
        """
        DO $$
        BEGIN
            ALTER TABLE agent_messages ADD COLUMN pending_data JSONB DEFAULT NULL;
        EXCEPTION
            WHEN duplicate_column THEN null;
        END $$;
        """,

        # 4. status 索引（部分索引，仅在 apply_pending 时生效）
        """
        CREATE INDEX IF NOT EXISTS idx_agent_messages_status
            ON agent_messages(status)
            WHERE status != 'normal';
        """,

        # 5. session + status 复合索引
        """
        CREATE INDEX IF NOT EXISTS idx_agent_messages_session_status
            ON agent_messages(session_id, status)
            WHERE status != 'normal';
        """,

        # 6. 添加注释
        """
        COMMENT ON COLUMN agent_messages.status IS '消息状态: normal=普通 | apply_pending=申请待确认';
        """,
        """
        COMMENT ON COLUMN agent_messages.pending_data IS 'HITL 待确认数据（JSON）';
        """,
    ]

    async with engine.begin() as conn:
        for sql in sqls:
            try:
                await conn.execute(text(sql))
                # 打印摘要
                snippet = sql[:80].strip().replace('\n', ' ').replace('  ', ' ')
                print("[OK]", snippet)
            except Exception as e:
                code = getattr(e, 'orig', None)
                if code and 'duplicate' in str(code).lower():
                    print("[SKIP] already exists:", sql[:60].strip().replace('\n', ' '))
                else:
                    print("[ERROR]", e)
                    raise

    await engine.dispose()
    print("\n迁移完成 ✓")
    print("\n验证查询（应返回 0 行或更多）：")
    print("  SELECT id, status, pending_data FROM agent_messages WHERE status = 'apply_pending' LIMIT 1;")


if __name__ == "__main__":
    asyncio.run(main())
