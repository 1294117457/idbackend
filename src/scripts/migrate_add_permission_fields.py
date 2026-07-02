"""数据库迁移脚本 - 添加 permission 表缺失的列

执行此脚本添加菜单相关字段：
    python -m src.scripts.migrate_add_permission_fields
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text
from src.infra.database import AsyncSessionLocal


async def migrate():
    """执行迁移"""
    async with AsyncSessionLocal() as db:
        try:
            print("开始迁移 permission 表...")

            # 添加 parent_id 列
            await db.execute(text("""
                ALTER TABLE permission 
                ADD COLUMN IF NOT EXISTS parent_id INTEGER REFERENCES permission(id) ON DELETE SET NULL
            """))
            print("[OK] parent_id 列已添加")

            # 添加 is_menu 列
            await db.execute(text("""
                ALTER TABLE permission 
                ADD COLUMN IF NOT EXISTS is_menu BOOLEAN DEFAULT FALSE
            """))
            print("[OK] is_menu 列已添加")

            # 添加 icon 列
            await db.execute(text("""
                ALTER TABLE permission 
                ADD COLUMN IF NOT EXISTS icon VARCHAR(100)
            """))
            print("[OK] icon 列已添加")

            # 添加 route_path 列
            await db.execute(text("""
                ALTER TABLE permission 
                ADD COLUMN IF NOT EXISTS route_path VARCHAR(255)
            """))
            print("[OK] route_path 列已添加")

            # 添加 component_path 列
            await db.execute(text("""
                ALTER TABLE permission 
                ADD COLUMN IF NOT EXISTS component_path VARCHAR(255)
            """))
            print("[OK] component_path 列已添加")

            await db.commit()
            print("\n[完成] 迁移成功！")

        except Exception as e:
            await db.rollback()
            print(f"[错误] 迁移失败: {e}")
            import traceback
            traceback.print_exc()
            raise


if __name__ == "__main__":
    print("=" * 50)
    print("Permission 表字段迁移")
    print("=" * 50)
    asyncio.run(migrate())
