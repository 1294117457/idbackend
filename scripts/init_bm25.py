"""BM25 中文全文索引初始化脚本

功能：
  1. 启用 zhparser 扩展
  2. 创建中文全文搜索配置 chinese_zh
  3. 给 embeddings 表加 content_tsv 列（generated）
  4. 建 GIN 索引
  5. 验证

用法：
  cd idbackend
  python3 scripts/init_bm25.py
"""
import asyncio
import sys
from pathlib import Path

# 让脚本能 import src.*
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.infra.config import get_async_database_url


DDL_STATEMENTS = [
    # 1. 启用 zhparser
    "CREATE EXTENSION IF NOT EXISTS zhparser;",

    # 2. 创建中文分词配置（IF NOT EXISTS 防止重复运行报错）
    """
    DO $$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM pg_ts_config WHERE cfgname = 'chinese_zh'
      ) THEN
        CREATE TEXT SEARCH CONFIGURATION chinese_zh (PARSER = zhparser);
        ALTER TEXT SEARCH CONFIGURATION chinese_zh
          ADD MAPPING FOR a,b,c,d,e,f,g,h,i,j,k,l,m,n,o,p,q,r,s,t,u,v,w,x,y,z
          WITH simple;
      END IF;
    END$$;
    """,

    # 3. 加 tsvector 列（generated column）
    """
    ALTER TABLE embeddings
      ADD COLUMN IF NOT EXISTS content_tsv tsvector
      GENERATED ALWAYS AS (
        setweight(to_tsvector('chinese_zh', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('chinese_zh', coalesce(content, '')), 'B')
      ) STORED;
    """,

    # 4. 建 GIN 索引
    """
    CREATE INDEX IF NOT EXISTS idx_embeddings_tsv
      ON embeddings USING GIN (content_tsv);
    """,
]


VERIFY_STATEMENTS = [
    # 扩展
    ("扩展", "SELECT extname, extversion FROM pg_extension WHERE extname IN ('zhparser', 'vector') ORDER BY extname;"),

    # 列
    ("content_tsv 列",
     """
     SELECT column_name, data_type, is_generated
     FROM information_schema.columns
     WHERE table_name = 'embeddings' AND column_name = 'content_tsv';
     """),

    # 索引
    ("GIN 索引",
     """
     SELECT indexname FROM pg_indexes
     WHERE tablename = 'embeddings' AND indexname = 'idx_embeddings_tsv';
     """),

    # 总数
    ("总数",
     "SELECT COUNT(*) AS total, COUNT(content_tsv) AS with_tsv FROM embeddings;"),

    # 测试：搜"学术专长"
    ("测试 1：搜「学术专长」",
     """
     SELECT id, LEFT(title, 40) AS title,
            ts_rank_cd(content_tsv, plainto_tsquery('chinese_zh', '学术专长')) AS rank
     FROM embeddings
     WHERE content_tsv @@ plainto_tsquery('chinese_zh', '学术专长')
     ORDER BY rank DESC LIMIT 5;
     """),

    # 测试：搜"Python 编程"
    ("测试 2：搜「Python 编程」",
     """
     SELECT id, LEFT(title, 40) AS title,
            ts_rank_cd(content_tsv, plainto_tsquery('chinese_zh', 'Python 编程')) AS rank
     FROM embeddings
     WHERE content_tsv @@ plainto_tsquery('chinese_zh', 'Python 编程')
     ORDER BY rank DESC LIMIT 5;
     """),
]


async def main():
    url = get_async_database_url()
    print(f"🔗 连接: {url}")
    print()

    engine = create_async_engine(url, echo=False)

    async with engine.begin() as conn:
        print("=" * 60)
        print("📦 执行 DDL")
        print("=" * 60)
        for i, sql in enumerate(DDL_STATEMENTS, 1):
            try:
                await conn.execute(text(sql))
                print(f"  [{i}/{len(DDL_STATEMENTS)}] OK")
            except Exception as e:
                print(f"  [{i}/{len(DDL_STATEMENTS)}] ✗ {e}")
                raise

        print()
        print("=" * 60)
        print("🔍 验证")
        print("=" * 60)
        for label, sql in VERIFY_STATEMENTS:
            print(f"\n📌 {label}")
            print("-" * 60)
            result = await conn.execute(text(sql))
            rows = result.fetchall()
            if not rows:
                print("  (无结果)")
            else:
                for row in rows:
                    print(f"  {tuple(row)}")

    await engine.dispose()

    print()
    print("=" * 60)
    print("✅ 完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())