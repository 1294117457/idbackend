"""迁移: ref_id + doc_id → source_id（统一来源标识）

操作：
1. 添加 source_id 列
2. 添加 chunk_index 列（如不存在）
3. 迁移旧数据：ref_id → source_id = 'tpl_{ref_id}', doc_id → source_id = doc_id
4. 删除旧列 ref_id, doc_id
5. 删除旧索引，创建新索引

用法:
    python -m src.scripts.migrate_to_source_id
"""
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.infra.config import get_async_database_url


STEPS = [
    # 1. 添加新列
    (
        "添加 source_id 列",
        "ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS source_id VARCHAR(64)",
    ),
    (
        "添加 chunk_index 列",
        "ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS chunk_index INTEGER DEFAULT 0",
    ),

    # 2. 迁移旧数据
    (
        "迁移 ref_id → source_id (tpl_xxx)",
        """
        UPDATE embeddings
        SET source_id = 'tpl_' || ref_id::text
        WHERE ref_id IS NOT NULL AND (source_id IS NULL OR source_id = '')
        """,
    ),
    (
        "迁移 doc_id → source_id",
        """
        UPDATE embeddings
        SET source_id = doc_id
        WHERE doc_id IS NOT NULL AND doc_id != ''
          AND (source_id IS NULL OR source_id = '')
        """,
    ),
    (
        "未迁移数据补默认 source_id",
        """
        UPDATE embeddings
        SET source_id = 'legacy_' || id::text
        WHERE source_id IS NULL OR source_id = ''
        """,
    ),

    # 3. 创建新索引
    (
        "创建 ix_embeddings_source_id 索引",
        "CREATE INDEX IF NOT EXISTS ix_embeddings_source_id ON embeddings (source_id)",
    ),

    # 4. 删除旧列（先删依赖索引）
    (
        "删除旧索引 ix_ref_id",
        "DROP INDEX IF EXISTS ix_ref_id",
    ),
    (
        "删除旧索引 ix_embeddings_ref_id",
        "DROP INDEX IF EXISTS ix_embeddings_ref_id",
    ),
    (
        "删除旧索引 ix_category_ref_id",
        "DROP INDEX IF EXISTS ix_category_ref_id",
    ),
    (
        "删除旧索引 ix_embeddings_category_ref_id",
        "DROP INDEX IF EXISTS ix_embeddings_category_ref_id",
    ),
    (
        "删除旧索引 ix_doc_id",
        "DROP INDEX IF EXISTS ix_doc_id",
    ),
    (
        "删除 ref_id 列",
        "ALTER TABLE embeddings DROP COLUMN IF EXISTS ref_id",
    ),
    (
        "删除 doc_id 列",
        "ALTER TABLE embeddings DROP COLUMN IF EXISTS doc_id",
    ),
]


async def main():
    engine = create_async_engine(get_async_database_url(), echo=False)

    for desc, sql in STEPS:
        async with engine.begin() as conn:
            try:
                await conn.execute(text(sql))
                print(f"  [OK] {desc}")
            except Exception as e:
                err = str(e).lower()
                if "does not exist" in err or "already exists" in err:
                    print(f" [SKIP] {desc} — {e}")
                else:
                    print(f"[FAIL] {desc} — {e}")
                    raise

    await engine.dispose()
    print("\n✓ 迁移完成: embeddings 表已统一为 source_id + chunk_index")


if __name__ == "__main__":
    asyncio.run(main())
