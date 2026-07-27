"""快速检查 system_config 表真实结构"""
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
        # 列信息
        result = await conn.execute(text("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'system_config' AND table_schema = 'public'
            ORDER BY ordinal_position;
        """))
        cols = list(result.fetchall())

        # 主键约束
        result = await conn.execute(text("""
            SELECT tc.constraint_name, tc.constraint_type, kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
            WHERE tc.table_name = 'system_config'
              AND tc.table_schema = 'public'
            ORDER BY tc.constraint_type;
        """))
        constraints = list(result.fetchall())

        # 行数
        result = await conn.execute(text("SELECT COUNT(*) FROM system_config;"))
        count = result.scalar_one()

        print("=" * 60)
        print("system_config 表结构")
        print("=" * 60)
        print(f"\n行数: {count}\n")

        print("列：")
        for r in cols:
            nullable = "NULL" if r.is_nullable == 'YES' else "NOT NULL"
            default = f"  default={r.column_default}" if r.column_default else ""
            print(f"  {r.column_name:<15} {r.data_type:<25} {nullable}{default}")

        print("\n约束：")
        for r in constraints:
            print(f"  {r.constraint_name:<30} {r.constraint_type:<15} ({r.column_name})")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
