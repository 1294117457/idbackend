"""数据库迁移脚本 - 删除 users 表的 role 冗余字段

执行：
    python -m src.scripts.migrate_drop_user_role_field
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.infra.database import AsyncSessionLocal
from sqlalchemy import text


async def migrate():
    async with AsyncSessionLocal() as db:
        try:
            print("开始迁移...")

            # 删除 role 列
            await db.execute(text("""
                ALTER TABLE users DROP COLUMN IF EXISTS role
            """))
            print("[OK] users.role 列已删除")

            await db.commit()
            print("\n[完成] 迁移成功！")

        except Exception as e:
            await db.rollback()
            print(f"[错误] {e}")
            raise


if __name__ == "__main__":
    asyncio.run(migrate())
