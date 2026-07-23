"""检查 embeddings 表的真实列名"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.infra.config import get_async_database_url


async def main():
    url = get_async_database_url()
    engine = create_async_engine(url, echo=False)

    async with engine.begin() as conn:
        print("=" * 60)
        print("📋 embeddings 表的所有列")
        print("=" * 60)
        result = await conn.execute(text("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'embeddings'
            ORDER BY ordinal_position;
        """))
        for row in result.fetchall():
            print(f"  {row.column_name:<35} {row.data_type:<30} nullable={row.is_nullable}")

        print()
        print("=" * 60)
        print("📊 数据行数")
        print("=" * 60)
        result = await conn.execute(text("SELECT COUNT(*) FROM embeddings"))
        print(f"  rows = {result.scalar_one()}")

        print()
        print("=" * 60)
        print("🔍 前 3 行样本（不显示 embedding 向量）")
        print("=" * 60)
        result = await conn.execute(text("""
            SELECT * FROM embeddings LIMIT 3;
        """))
        rows = result.mappings().all()
        for i, r in enumerate(rows):
            # 过滤掉太长的字段
            sample = {k: (v[:80] + '...' if isinstance(v, str) and len(v) > 80 else v)
                      for k, v in r.items() if k != 'embedding'}
            print(f"  row[{i}]: {sample}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())