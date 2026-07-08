"""手动完成迁移 015 的剩余步骤

由于迁移脚本在 Step 3 中断，需要运行此脚本完成剩余工作。

执行：python migrations/015_complete_migration.py
"""
import sys
sys.path.insert(0, '.')

from sqlalchemy import text
from src.infra.database import sync_engine


def table_exists(conn, table_name: str) -> bool:
    """检查表是否存在"""
    result = conn.execute(text("""
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = :t LIMIT 1
    """), {"t": table_name})
    return result.first() is not None


def complete_migration():
    print("=" * 70)
    print("手动完成迁移 015 剩余步骤")
    print("=" * 70)

    with sync_engine.begin() as conn:
        # 确定表名
        applications_table = "applications" if table_exists(conn, "applications") else "score_applications"
        print(f"\n检测到主表: {applications_table}")

        # Step 3: 更新 application_operation 外键
        print("\n[Step 3] 更新 application_operation 外键...")
        conn.execute(text("""
            ALTER TABLE application_operation
            DROP CONSTRAINT IF EXISTS application_operation_application_id_fkey
        """))
        conn.execute(text(f"""
            ALTER TABLE application_operation
            ADD CONSTRAINT application_operation_application_id_fkey
            FOREIGN KEY (application_id) REFERENCES {applications_table}(id) ON DELETE CASCADE
        """))
        print("    ✓ application_operation 外键已更新")

        # Step 4: 更新 application_proofs 外键
        print("\n[Step 4] 更新 application_proofs 外键...")
        conn.execute(text("""
            ALTER TABLE application_proofs
            DROP CONSTRAINT IF EXISTS application_proofs_application_id_fkey
        """))
        conn.execute(text(f"""
            ALTER TABLE application_proofs
            ADD CONSTRAINT application_proofs_application_id_fkey
            FOREIGN KEY (application_id) REFERENCES {applications_table}(id) ON DELETE CASCADE
        """))
        print("    ✓ application_proofs 外键已更新")

        # Step 5: 更新 score_data 外键
        print("\n[Step 5] 更新 score_data 外键...")
        conn.execute(text("""
            ALTER TABLE score_data
            DROP CONSTRAINT IF EXISTS score_data_application_id_fkey
        """))
        conn.execute(text(f"""
            ALTER TABLE score_data
            ADD CONSTRAINT score_data_application_id_fkey
            FOREIGN KEY (application_id) REFERENCES {applications_table}(id) ON DELETE CASCADE
        """))
        print("    ✓ score_data 外键已更新")

        # Step 6: 重命名索引
        print("\n[Step 6] 重命名索引...")
        old_prefix = "score_applications" if applications_table == "applications" else ""
        new_prefix = "applications"

        index_renames = [
            ("idx_application_user_template_status", "idx_applications_user_template_status"),
            ("idx_application_status", "idx_applications_status"),
            ("idx_application_category", "idx_applications_category"),
        ]
        for old_idx, new_idx in index_renames:
            try:
                conn.execute(text(f"ALTER INDEX {old_idx} RENAME TO {new_idx}"))
                print(f"    ✓ {old_idx} → {new_idx}")
            except Exception as e:
                print(f"    - {old_idx}: {e}")

        # Step 7: 更新序列所有权
        print("\n[Step 7] 更新序列所有权...")
        conn.execute(text(f"""
            ALTER SEQUENCE {applications_table}_id_seq OWNED BY {applications_table}.id
        """))
        print("    ✓ 序列所有权已更新")

    print("\n" + "=" * 70)
    print("迁移 015 手动步骤完成！")
    print("=" * 70)
    print("\n验证:")
    print("  SELECT * FROM applications LIMIT 1;")
    print("  SELECT approved_count FROM applications LIMIT 1;")
    print("  重启 idpython 服务")


if __name__ == "__main__":
    complete_migration()
