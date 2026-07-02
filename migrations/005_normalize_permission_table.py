"""迁移脚本：规范化 permission 表结构

将数据库字段对齐到最新模型：
- permission_code → code（重命名）
- permission_name → name（重命名）
- 删除：module, is_menu, icon, component_path

最终保留字段：id, code, name, route_path, description, sort_order, status, created_at, updated_at

执行前请备份数据库！
"""

import sys
sys.path.insert(0, '.')

from sqlalchemy import text
from src.infra.database import sync_engine


def get_columns(conn):
    result = conn.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'permission'
    """))
    return [row[0] for row in result.fetchall()]


def migrate():
    print("开始规范化 permission 表...")

    with sync_engine.connect() as conn:
        # 检查表存在
        exists = conn.execute(text(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'permission')"
        )).scalar()
        if not exists:
            print("permission 表不存在，跳过")
            return False

        columns = get_columns(conn)
        print(f"当前字段: {columns}")

        # 1. 重命名 permission_code -> code
        if 'permission_code' in columns and 'code' not in columns:
            conn.execute(text("ALTER TABLE permission RENAME COLUMN permission_code TO code"))
            print("重命名: permission_code -> code")
        elif 'code' in columns:
            print("code 字段已存在，跳过重命名")

        # 2. 重命名 permission_name -> name
        if 'permission_name' in columns and 'name' not in columns:
            conn.execute(text("ALTER TABLE permission RENAME COLUMN permission_name TO name"))
            print("重命名: permission_name -> name")
        elif 'name' in columns:
            print("name 字段已存在，跳过重命名")

        # 3. 删除多余字段
        columns = get_columns(conn)  # 重新读取（重命名后字段名变了）
        to_drop = ['module', 'is_menu', 'icon', 'component_path']
        for col in to_drop:
            if col in columns:
                conn.execute(text(f"ALTER TABLE permission DROP COLUMN IF EXISTS {col}"))
                print(f"删除字段: {col}")
            else:
                print(f"{col} 不存在，跳过")

        conn.commit()

        # 验证
        final_columns = get_columns(conn)
        print(f"\npermission 表最终字段: {sorted(final_columns)}")
        print("\n迁移完成！")
        return True


def rollback():
    """回滚：恢复字段名和已删除列（数据已丢失，仅恢复结构）"""
    print("回滚迁移...")

    with sync_engine.connect() as conn:
        columns = get_columns(conn)

        if 'code' in columns and 'permission_code' not in columns:
            conn.execute(text("ALTER TABLE permission RENAME COLUMN code TO permission_code"))
            print("回滚: code -> permission_code")

        if 'name' in columns and 'permission_name' not in columns:
            conn.execute(text("ALTER TABLE permission RENAME COLUMN name TO permission_name"))
            print("回滚: name -> permission_name")

        conn.execute(text("ALTER TABLE permission ADD COLUMN IF NOT EXISTS module VARCHAR(50) NOT NULL DEFAULT 'default'"))
        conn.execute(text("ALTER TABLE permission ADD COLUMN IF NOT EXISTS is_menu BOOLEAN DEFAULT FALSE"))
        conn.execute(text("ALTER TABLE permission ADD COLUMN IF NOT EXISTS icon VARCHAR(100)"))
        conn.execute(text("ALTER TABLE permission ADD COLUMN IF NOT EXISTS component_path VARCHAR(255)"))
        conn.commit()
        print("回滚完成（数据已丢失，仅恢复结构）")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--rollback', action='store_true', help='回滚迁移')
    args = parser.parse_args()

    if args.rollback:
        rollback()
    else:
        migrate()
