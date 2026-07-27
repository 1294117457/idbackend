"""创建 AI Chat 相关表

用法:
    python -m src.scripts.migrate_create_ai_chat_tables
"""
import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.infra.config import get_async_database_url as get_database_url


async def main():
    engine = create_async_engine(get_database_url(), echo=False)

    sqls = [
        # 删除旧表和枚举（如果存在）
        """
        DROP TABLE IF EXISTS agent_session_snapshots CASCADE;
        """,
        """
        DROP TABLE IF EXISTS agent_session_summaries CASCADE;
        """,
        """
        DROP TABLE IF EXISTS agent_messages CASCADE;
        """,
        """
        DROP TABLE IF EXISTS agent_sessions CASCADE;
        """,
        """
        DROP TYPE IF EXISTS sessionstatus CASCADE;
        """,
        """
        DROP TYPE IF EXISTS messagerole CASCADE;
        """,
        """
        DROP TYPE IF EXISTS messagetype CASCADE;
        """,

        # Enum 类型
        """
        CREATE TYPE sessionstatus AS ENUM ('ACTIVE', 'ARCHIVED');
        """,
        """
        CREATE TYPE messagerole AS ENUM ('USER', 'ASSISTANT', 'SYSTEM');
        """,
        """
        CREATE TYPE messagetype AS ENUM ('TEXT', 'SUGGESTION', 'INTERRUPT');
        """,

        # agent_sessions 表
        """
        CREATE TABLE IF NOT EXISTS agent_sessions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title VARCHAR(200) NOT NULL DEFAULT '新会话',
            status sessionstatus NOT NULL DEFAULT 'ACTIVE',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_agent_sessions_user_id ON agent_sessions(user_id);
        """,

        # agent_messages 表
        """
        CREATE TABLE IF NOT EXISTS agent_messages (
            id SERIAL PRIMARY KEY,
            session_id INTEGER NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
            role messagerole NOT NULL,
            content TEXT NOT NULL,
            msg_type messagetype NOT NULL DEFAULT 'TEXT',
            sources JSONB,
            tool_calls JSONB,
            seq INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_agent_messages_session_id ON agent_messages(session_id);
        """,

        # agent_session_summaries 表
        """
        CREATE TABLE IF NOT EXISTS agent_session_summaries (
            id SERIAL PRIMARY KEY,
            session_id INTEGER NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
            summary TEXT NOT NULL,
            start_seq INTEGER NOT NULL DEFAULT 0,
            end_seq INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_agent_session_summaries_session_id ON agent_session_summaries(session_id);
        """,

        # agent_session_snapshots 表
        """
        CREATE TABLE IF NOT EXISTS agent_session_snapshots (
            id SERIAL PRIMARY KEY,
            session_id INTEGER NOT NULL UNIQUE REFERENCES agent_sessions(id) ON DELETE CASCADE,
            message_count INTEGER NOT NULL DEFAULT 0,
            last_message_at TIMESTAMP WITH TIME ZONE,
            needs_compress BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_agent_session_snapshots_session_id ON agent_session_snapshots(session_id);
        """,
    ]

    async with engine.begin() as conn:
        for sql in sqls:
            try:
                await conn.execute(text(sql))
                print("[OK]", sql[:80].strip().replace('\n', ' '))
            except Exception as e:
                if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                    print("[SKIP] already exists:", sql[:60].strip().replace('\n', ' '))
                else:
                    print("[ERROR]", e)
                    raise

    await engine.dispose()
    print("\ndone")


if __name__ == "__main__":
    asyncio.run(main())
