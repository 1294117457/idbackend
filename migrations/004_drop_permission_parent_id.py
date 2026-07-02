"""迁移脚本：移除 permission 表的 parent_id 字段

此迁移脚本将：
1. 删除 permission.parent_id 外键约束
2. 删除 permission.parent_id 列

执行前请备份数据库！
"""

import sys
sys.path.insert(0, '.')

from sqlalchemy import text
from src.infra.database import sync_engine


def migrate():
    """执行迁移"""
    print("开始移除 permission.parent_id 字段...")

    with sync_engine.connect() as conn:
        # 检查表是否存在
        result = conn.execute(text(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'permission')"
        ))
        if not result.scalar():
            print("permission 表不存在，跳过")
            return False

        # 检查 parent_id 列是否存在
        check = conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'permission' AND column_name = 'parent_id'
        """))
        if not check.fetchone():
            print("parent_id 列不存在，无需迁移")
            return True

        # 查找并删除外键约束
        fk_result = conn.execute(text("""
            SELECT conname FROM pg_constraint
            WHERE conrelid = 'permission'::regclass
              AND contype = 'f'
              AND conname LIKE '%parent_id%'
        """))
        for row in fk_result.fetchall():
            fk_name = row[0]
            conn.execute(text(f'ALTER TABLE permission DROP CONSTRAINT IF EXISTS "{fk_name}"'))
            print(f"已删除外键约束: {fk_name}")

        # 删除 parent_id 列
        conn.execute(text("ALTER TABLE permission DROP COLUMN IF EXISTS parent_id"))
        conn.commit()
        print("已删除列: parent_id")

        # 验证
        check_after = conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'permission'
            ORDER BY ordinal_position
        """))
        print("\npermission 表当前字段:")
        for row in check_after.fetchall():
            print(f"  - {row[0]}")

        print("\n迁移完成！")
        return True


def rollback():
    """回滚：重新添加 parent_id 列（数据已丢失，仅恢复结构）"""
    print("回滚迁移：重新添加 parent_id 列...")

    with sync_engine.connect() as conn:
        conn.execute(text("""
            ALTER TABLE permission
            ADD COLUMN IF NOT EXISTS parent_id INTEGER
            REFERENCES permission(id) ON DELETE SET NULL
        """))
        conn.commit()
        print("已重新添加 parent_id 列（数据已丢失，仅恢复结构）")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--rollback', action='store_true', help='回滚迁移')
    args = parser.parse_args()

    if args.rollback:
        rollback()
    else:
        migrate()
