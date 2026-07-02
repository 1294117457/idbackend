"""迁移脚本：添加 RBAC 表约束和索引

根据 RBAC 最终设计文档（第 10 节），添加以下数据库约束：

1. `user_role` 表：
   - 唯一约束 (user_id, role_id)
   - 索引 user_id
   - 索引 role_id

2. `role_permission` 表：
   - 唯一约束 (role_id, permission_id)
   - 索引 role_id
   - 索引 permission_id

3. `permission` 表：
   - 索引 api_path（用于接口权限映射查询加速）

4. `role` 表：
   - 唯一约束 role_code（已有）
   - 索引 role_code

5. `users` 表：
   - 唯一约束 username（已有）

执行前请备份数据库！
"""

import sys
sys.path.insert(0, '.')

from sqlalchemy import text
from src.infra.database import sync_engine


def get_indexes(conn, table_name):
    """获取表的索引信息"""
    result = conn.execute(text("""
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE tablename = :table
    """), {"table": table_name})
    return [(row[0], row[1]) for row in result.fetchall()]


def get_constraints(conn, table_name):
    """获取表的约束信息"""
    # 注意：这里直接用 f-string，因为 conrelid = :table::regclass 不支持参数化
    result = conn.execute(text(f"""
        SELECT conname, pg_get_constraintdef(oid)
        FROM pg_constraint
        WHERE conrelid = '{table_name}'::regclass
    """))
    return [(row[0], row[1]) for row in result.fetchall()]


def migrate():
    print("开始添加 RBAC 表约束和索引...")

    with sync_engine.connect() as conn:
        # ========== 1. user_role 表 ==========
        print("\n[1/3] 处理 user_role 表...")

        existing_indexes = get_indexes(conn, 'user_role')
        existing_constraints = get_constraints(conn, 'user_role')
        index_names = [idx[0] for idx in existing_indexes]
        constraint_names = [c[0] for c in existing_constraints]

        # 唯一约束
        if 'user_role_user_id_role_id_unique' not in constraint_names:
            try:
                conn.execute(text("""
                    ALTER TABLE user_role
                    ADD CONSTRAINT user_role_user_id_role_id_unique
                    UNIQUE (user_id, role_id)
                """))
                print("  + 添加唯一约束: (user_id, role_id)")
            except Exception as e:
                print(f"  ! 唯一约束可能已存在: {e}")
        else:
            print("  ✓ 唯一约束 (user_id, role_id) 已存在")

        # 索引 user_id
        if 'idx_user_role_user_id' not in index_names:
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_user_role_user_id ON user_role(user_id)"))
            print("  + 添加索引: idx_user_role_user_id ON user_id")
        else:
            print("  ✓ 索引 idx_user_role_user_id 已存在")

        # 索引 role_id
        if 'idx_user_role_role_id' not in index_names:
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_user_role_role_id ON user_role(role_id)"))
            print("  + 添加索引: idx_user_role_role_id ON role_id")
        else:
            print("  ✓ 索引 idx_user_role_role_id 已存在")

        # ========== 2. role_permission 表 ==========
        print("\n[2/3] 处理 role_permission 表...")

        existing_indexes = get_indexes(conn, 'role_permission')
        existing_constraints = get_constraints(conn, 'role_permission')
        index_names = [idx[0] for idx in existing_indexes]
        constraint_names = [c[0] for c in existing_constraints]

        # 唯一约束
        if 'role_permission_role_id_permission_id_unique' not in constraint_names:
            try:
                conn.execute(text("""
                    ALTER TABLE role_permission
                    ADD CONSTRAINT role_permission_role_id_permission_id_unique
                    UNIQUE (role_id, permission_id)
                """))
                print("  + 添加唯一约束: (role_id, permission_id)")
            except Exception as e:
                print(f"  ! 唯一约束可能已存在: {e}")
        else:
            print("  ✓ 唯一约束 (role_id, permission_id) 已存在")

        # 索引 role_id
        if 'idx_role_permission_role_id' not in index_names:
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_role_permission_role_id ON role_permission(role_id)"))
            print("  + 添加索引: idx_role_permission_role_id ON role_id")
        else:
            print("  ✓ 索引 idx_role_permission_role_id 已存在")

        # 索引 permission_id
        if 'idx_role_permission_permission_id' not in index_names:
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_role_permission_permission_id ON role_permission(permission_id)"))
            print("  + 添加索引: idx_role_permission_permission_id ON permission_id")
        else:
            print("  ✓ 索引 idx_role_permission_permission_id 已存在")

        # ========== 3. permission 表 ==========
        print("\n[3/3] 处理 permission 表...")

        existing_indexes = get_indexes(conn, 'permission')
        index_names = [idx[0] for idx in existing_indexes]

        # 索引 api_path
        if 'idx_permission_api_path' not in index_names:
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_permission_api_path ON permission(api_path)"))
            print("  + 添加索引: idx_permission_api_path ON api_path")
        else:
            print("  ✓ 索引 idx_permission_api_path 已存在")

        # 唯一约束 permission_code（如果不存在）
        existing_constraints = get_constraints(conn, 'permission')
        constraint_names = [c[0] for c in existing_constraints]
        if 'permission_permission_code_key' not in constraint_names:
            try:
                conn.execute(text("ALTER TABLE permission ADD CONSTRAINT permission_permission_code_key UNIQUE (permission_code)"))
                print("  + 添加唯一约束: permission_code")
            except Exception as e:
                print(f"  ! permission_code 唯一约束可能已存在: {e}")
        else:
            print("  ✓ 唯一约束 permission_code 已存在")

        conn.commit()

        # ========== 验证 ==========
        print("\n" + "=" * 50)
        print("验证结果:")
        print("=" * 50)

        for table in ['user_role', 'role_permission', 'permission']:
            print(f"\n{table} 表:")
            indexes = get_indexes(conn, table)
            constraints = get_constraints(conn, table)
            for name, defn in indexes:
                print(f"  索引: {name}")
            for name, defn in constraints:
                print(f"  约束: {name} ({defn})")

        print("\n" + "=" * 50)
        print("迁移完成！")
        print("=" * 50)
        return True


def rollback():
    """回滚：删除添加的约束和索引"""
    print("回滚迁移...")

    with sync_engine.connect() as conn:
        # 删除 user_role 约束和索引
        conn.execute(text("DROP INDEX IF EXISTS idx_user_role_user_id"))
        conn.execute(text("DROP INDEX IF EXISTS idx_user_role_role_id"))
        conn.execute(text("ALTER TABLE user_role DROP CONSTRAINT IF EXISTS user_role_user_id_role_id_unique"))

        # 删除 role_permission 约束和索引
        conn.execute(text("DROP INDEX IF EXISTS idx_role_permission_role_id"))
        conn.execute(text("DROP INDEX IF EXISTS idx_role_permission_permission_id"))
        conn.execute(text("ALTER TABLE role_permission DROP CONSTRAINT IF EXISTS role_permission_role_id_permission_id_unique"))

        # 删除 permission 索引
        conn.execute(text("DROP INDEX IF EXISTS idx_permission_api_path"))

        conn.commit()
        print("回滚完成！")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--rollback', action='store_true', help='回滚迁移')
    args = parser.parse_args()

    if args.rollback:
        rollback()
    else:
        migrate()
