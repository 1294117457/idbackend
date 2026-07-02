"""迁移脚本：为 permission 表添加 route_path 索引

此迁移脚本将：
1. 给 route_path 字段添加索引以加速权限鉴权查询
2. 给 code 字段添加唯一索引（如果还没有）

执行前请备份数据库！
"""

import sys
sys.path.insert(0, '.')

from sqlalchemy import text
from src.core.database import engine


def migrate():
    """执行迁移"""
    print("🚀 开始添加 permission 表索引...")

    with engine.connect() as conn:
        # 1. 检查表是否存在
        result = conn.execute(text(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'permission')"
        ))
        if not result.scalar():
            print("❌ permission 表不存在，请先运行初始化")
            return False

        # 2. 检查 route_path 列是否存在
        check_columns = conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'permission'
        """))
        columns = [row[0] for row in check_columns.fetchall()]

        if 'route_path' not in columns:
            print("❌ route_path 列不存在，请先运行 002 迁移")
            return False

        # 3. 添加 route_path 索引
        print("📝 添加 route_path 索引...")

        # 检查索引是否已存在
        check_idx = conn.execute(text("""
            SELECT 1 FROM pg_indexes WHERE tablename = 'permission' AND indexname = 'idx_permission_route_path'
        """))
        if check_idx.fetchone():
            print("   ⏭️  索引 idx_permission_route_path 已存在，跳过")
        else:
            conn.execute(text("""
                CREATE INDEX idx_permission_route_path ON permission(route_path)
            """))
            conn.commit()
            print("   ✅ 已添加索引: idx_permission_route_path")

        # 4. 添加 code 唯一索引（如果还没有）
        print("📝 检查 code 字段索引...")
        check_unique = conn.execute(text("""
            SELECT 1 FROM pg_indexes WHERE tablename = 'permission' AND indexname = 'idx_permission_code'
        """))
        if check_unique.fetchone():
            print("   ⏭️  索引 idx_permission_code 已存在，跳过")
        else:
            # 注意：PostgreSQL 的唯一约束会自动创建索引
            # 如果 code 已经有唯一约束，则不需要单独建索引
            conn.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_permission_code ON permission(code)
            """))
            conn.commit()
            print("   ✅ 已添加索引: idx_permission_code")

        # 5. 列出所有索引
        print("\n📋 permission 表索引列表:")
        list_idx = conn.execute(text("""
            SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'permission'
        """))
        for row in list_idx.fetchall():
            print(f"   - {row[0]}")

        print("\n✅ 迁移完成！")
        return True


def rollback():
    """回滚迁移"""
    print("🔄 回滚迁移...")

    with engine.connect() as conn:
        try:
            conn.execute(text("DROP INDEX IF EXISTS idx_permission_route_path"))
            conn.execute(text("DROP INDEX IF EXISTS idx_permission_code"))
            conn.commit()
            print("✅ 索引已删除")
        except Exception as e:
            print(f"❌ 回滚失败: {e}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--rollback', action='store_true', help='回滚迁移')
    args = parser.parse_args()

    if args.rollback:
        rollback()
    else:
        migrate()
