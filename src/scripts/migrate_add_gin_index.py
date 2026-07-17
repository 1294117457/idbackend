"""为 reviewer_ids JSONB 字段添加 GIN 索引

应用场景:
  - reviewer_ids::jsonb @> to_jsonb(?)::jsonb
    → list_pending_for_me 查询审核员的待审核列表

用法:
    python -m src.scripts.migrate_add_gin_index
"""
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.infra.config import get_async_database_url as get_database_url


async def main():
    engine = create_async_engine(get_database_url(), echo=False)

    sqls = [
        # GIN 索引: applications 表 reviewer_ids JSONB 字段
        # 使用 jsonb_path_ops 操作符，只支持 @> 查询，性能最优
        """
        CREATE INDEX IF NOT EXISTS idx_applications_reviewer_ids_gin
        ON applications USING gin (reviewer_ids jsonb_path_ops)
        """,
    ]

    async with engine.begin() as conn:
        for sql in sqls:
            try:
                await conn.execute(text(sql))
                print("[OK]", sql[:60].strip())
            except Exception as e:
                if "already exists" in str(e):
                    print("[SKIP] already exists:", sql[:60].strip())
                else:
                    raise

    await engine.dispose()
    print("done")


if __name__ == "__main__":
    asyncio.run(main())
