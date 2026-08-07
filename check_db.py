"""查 template id=41 的 description 真实值（直接 SQL，不走 ORM）。"""
import asyncio
import sys


async def main():
    from src.infra.database import AsyncSessionLocal
    from sqlalchemy import text

    async with AsyncSessionLocal() as db:
        r = await db.execute(
            text("SELECT id, description FROM template WHERE id = 41")
        )
        row = r.first()
        if row is None:
            print("template id=41 不存在")
            return
        print(f"id={row[0]}")
        print(f"description (全文):")
        print(row[1])
        print()
        print(f"contains 'editor://' ? {'editor://' in (row[1] or '')}")
        print(f"contains 'X-Amz' ? {'X-Amz' in (row[1] or '')}")
        print(f"contains 'style=' ? {'style=' in (row[1] or '')}")
        print(f"contains '<br>' ? {'<br>' in (row[1] or '')}")


if __name__ == "__main__":
    asyncio.run(main())
