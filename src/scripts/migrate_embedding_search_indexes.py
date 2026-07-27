"""为 embeddings 表添加搜索索引

改动：
1. 向量索引（HNSW）：加速 pgvector 余弦距离检索 — 需要 pgvector >= 0.5.0
2. tsvector 列：对 title + content 生成全文检索向量（BM25 关键词匹配，中文分词）
3. GIN 索引：加速 tsvector 的全文检索查询

注意：
- 向量索引需要 pgvector 扩展已安装（pgvector/pgvector:pg16 镜像自带）
- BM25 全文检索需要 zhparser 扩展已安装（如不支持，会跳过向量索引，只建 BM25 全文检索）
- tsvector 是 GENERATED ALWAYS AS 列，重建列后已有数据会自动重新计算，无需单独 UPDATE

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

    # 确保 zhparser 扩展已启用（BM25 中文分词依赖）
    await run_sql(engine, "CREATE EXTENSION IF NOT EXISTS zhparser")

    # HNSW 向量索引（需要 pgvector >= 0.5.0，不支持则跳过）
    await run_sql(engine, """
        CREATE INDEX IF NOT EXISTS idx_embeddings_hnsw
        ON embeddings USING hnsw (embedding vector_cosine_ops)
    """, skippable=True)

    # 检查是否已存在 content_tsv 列，如有则先删除（GENERATED ALWAYS AS 列不能直接 UPDATE，只能重建）
    async with engine.begin() as conn:
        result = await conn.execute(text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'embeddings' AND column_name = 'content_tsv'
        """))
        if result.fetchone():
            print("[INFO] 检测到 content_tsv 列，重新构建为 chinese_zh 分词...")
            # 重建 tsvector 生成列（GENERATED ALWAYS AS 列重建后会自动重算已有数据）
            await run_sql(engine, """
                ALTER TABLE embeddings DROP COLUMN IF EXISTS content_tsv
            """)
            await run_sql(engine, """
                ALTER TABLE embeddings
                ADD COLUMN content_tsv tsvector
                GENERATED ALWAYS AS (
                    to_tsvector('chinese_zh', coalesce(title, '') || ' ' || coalesce(content, ''))
                ) STORED
            """)
        else:
            # 新建 tsvector 生成列
            await run_sql(engine, """
                ALTER TABLE embeddings
                ADD COLUMN IF NOT EXISTS content_tsv tsvector
                GENERATED ALWAYS AS (
                    to_tsvector('chinese_zh', coalesce(title, '') || ' ' || coalesce(content, ''))
                ) STORED
            """)

    # GIN 索引：加速 tsvector 全文检索
    await run_sql(engine, """
        CREATE INDEX IF NOT EXISTS idx_embeddings_content_tsv
        ON embeddings USING gin (content_tsv)
    """)

    await engine.dispose()
    print("\n[OK] 迁移完成")


if __name__ == "__main__":
    asyncio.run(main())
