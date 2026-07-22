"""为 embeddings 表添加搜索索引

改动：
1. 向量索引（HNSW）：加速 pgvector 余弦距离检索 — 需要 pgvector >= 0.5.0
2. tsvector 列：对 title + content 生成全文检索向量（BM25 关键词匹配）
3. GIN 索引：加速 tsvector 的全文检索查询

注意：向量索引需要 pgvector 扩展已安装（pgvector/pgvector:pg16 镜像自带）
如果当前数据库不支持，会跳过向量索引，只建 BM25 全文检索。

用法:
    python -m src.scripts.migrate_embedding_search_indexes
"""
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.infra.config import get_async_database_url as get_database_url


async def run_sql(engine, sql: str, *, skippable: bool = False) -> bool:
    """单独事务执行一条 SQL，失败不影响后续。"""
    async with engine.begin() as conn:
        try:
            await conn.execute(text(sql))
            print("[OK]", sql.strip().split("\n")[0][:80])
            return True
        except Exception as e:
            err_msg = str(e).lower()
            if "already exists" in err_msg or "duplicate" in err_msg:
                print("[SKIP] already exists:", sql.strip().split("\n")[0][:60])
            elif skippable:
                print("[SKIP] not supported:", sql.strip().split("\n")[0][:60])
            else:
                print("[ERROR]", e)
                raise
            return False


async def main():
    engine = create_async_engine(get_database_url(), echo=False)

    # 确保 pgvector 扩展已启用
    await run_sql(engine, "CREATE EXTENSION IF NOT EXISTS vector")

    # HNSW 向量索引（需要 pgvector >= 0.5.0，不支持则跳过）
    await run_sql(engine, """
        CREATE INDEX IF NOT EXISTS idx_embeddings_hnsw
        ON embeddings USING hnsw (embedding vector_cosine_ops)
    """, skippable=True)

    # BM25 全文检索：tsvector 生成列
    await run_sql(engine, """
        ALTER TABLE embeddings
        ADD COLUMN IF NOT EXISTS content_tsv tsvector
        GENERATED ALWAYS AS (
            to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(content, ''))
        ) STORED
    """)

    # GIN 索引：加速 tsvector 全文检索
    await run_sql(engine, """
        CREATE INDEX IF NOT EXISTS idx_embeddings_content_tsv
        ON embeddings USING gin (content_tsv)
    """)

    await engine.dispose()
    print("\n✓ 迁移完成")


if __name__ == "__main__":
    asyncio.run(main())
