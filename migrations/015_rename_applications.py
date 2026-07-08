"""迁移 015：表重命名 + 修复 approved_count

执行：python migrations/015_rename_applications.py
"""
import sys
sys.path.insert(0, '.')

from sqlalchemy import text
from src.infra.database import sync_engine


def table_exists(conn, table_name: str) -> bool:
    result = conn.execute(text("""
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = :t LIMIT 1
    """), {"t": table_name})
    return result.first() is not None


def get_foreign_keys(conn, table_name: str, ref_table: str) -> list:
    """获取指向 ref_table 的外键名称列表"""
    result = conn.execute(text(f"""
        SELECT conname FROM pg_constraint
        WHERE conrelid = '{table_name}'::regclass
          AND contype = 'f'
          AND confrelid = '{ref_table}'::regclass
    """))
    return [row[0] for row in result]


def migrate():
    print("=" * 70)
    print("迁移 015：表重命名 + 修复 approved_count")
    print("=" * 70)

    with sync_engine.begin() as conn:
        old_table = "score_applications"
        new_table = "applications"

        # ---------- Step 1: 删除 evaluation_applications ----------
        print("\n[Step 1] 删除 evaluation_applications 表...")
        if table_exists(conn, "evaluation_applications"):
            conn.execute(text("DROP TABLE evaluation_applications CASCADE"))
            print("    ✓ evaluation_applications 已删除")
        else:
            print("    - evaluation_applications 不存在，跳过")

        # ---------- Step 2: 删除旧外键 ----------
        print("\n[Step 2] 删除旧外键约束...")

        for fk_name in get_foreign_keys(conn, "application_operation", old_table):
            conn.execute(text(f'ALTER TABLE application_operation DROP CONSTRAINT "{fk_name}"'))
            print(f"    - application_operation: {fk_name}")

        for fk_name in get_foreign_keys(conn, "application_proofs", old_table):
            conn.execute(text(f'ALTER TABLE application_proofs DROP CONSTRAINT "{fk_name}"'))
            print(f"    - application_proofs: {fk_name}")

        for fk_name in get_foreign_keys(conn, "score_data", old_table):
            conn.execute(text(f'ALTER TABLE score_data DROP CONSTRAINT "{fk_name}"'))
            print(f"    - score_data: {fk_name}")

        for fk_name in get_foreign_keys(conn, old_table, old_table):
            if "user_id" in fk_name.lower() or "rule_id" in fk_name.lower() or "template_id" in fk_name.lower() or "category_id" in fk_name.lower():
                conn.execute(text(f'ALTER TABLE {old_table} DROP CONSTRAINT "{fk_name}"'))
                print(f"    - {old_table}: {fk_name}")

        # ---------- Step 3: 重命名表 ----------
        print(f"\n[Step 3] 重命名表: {old_table} → {new_table}")

        conn.execute(text(f'ALTER TABLE {old_table} RENAME CONSTRAINT score_applications_pkey TO applications_pkey'))
        print("    ✓ 主键约束已重命名")

        conn.execute(text(f'ALTER TABLE {old_table} RENAME TO {new_table}'))
        print("    ✓ 表已重命名")

        # 查找实际的序列名
        result = conn.execute(text(f"""
            SELECT s.relname FROM pg_class s
            JOIN pg_depend d ON d.objid = s.oid
            WHERE d.refobjid = '{new_table}'::regclass
              AND s.relkind = 'S'
        """))
        seq_rows = result.fetchall()
        if seq_rows:
            old_seq = seq_rows[0][0]
            new_seq = f"{new_table}_id_seq"
            if old_seq != new_seq:
                conn.execute(text(f'ALTER SEQUENCE {old_seq} RENAME TO {new_seq}'))
                print(f"    ✓ 序列 {old_seq} → {new_seq}")
            else:
                print(f"    ✓ 序列已是 {new_seq}")
        else:
            print("    - 未找到关联序列，跳过")

        # ---------- Step 4: 添加 approved_count ----------
        print("\n[Step 4] 添加 approved_count 字段...")
        result = conn.execute(text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = :t AND column_name = :c
        """), {"t": new_table, "c": "approved_count"})

        if result.first() is None:
            conn.execute(text(f"""
                ALTER TABLE {new_table}
                ADD COLUMN approved_count INTEGER DEFAULT 0 NOT NULL
            """))
            print("    + approved_count INTEGER DEFAULT 0 NOT NULL")
        else:
            print("    ✓ approved_count 已存在")

        # ---------- Step 5: 创建新外键 ----------
        print("\n[Step 5] 创建新外键约束...")

        # 检查是否已有外键
        existing = get_foreign_keys(conn, "application_operation", new_table)
        if not existing:
            conn.execute(text(f"""
                ALTER TABLE application_operation
                ADD CONSTRAINT application_operation_application_id_fkey
                FOREIGN KEY (application_id) REFERENCES {new_table}(id) ON DELETE CASCADE
            """))
            print("    + application_operation_application_id_fkey")
        else:
            print(f"    - application_operation: 已存在 ({existing[0]})")

        existing = get_foreign_keys(conn, "application_proofs", new_table)
        if not existing:
            conn.execute(text(f"""
                ALTER TABLE application_proofs
                ADD CONSTRAINT application_proofs_application_id_fkey
                FOREIGN KEY (application_id) REFERENCES {new_table}(id) ON DELETE CASCADE
            """))
            print("    + application_proofs_application_id_fkey")
        else:
            print(f"    - application_proofs: 已存在 ({existing[0]})")

        existing = get_foreign_keys(conn, "score_data", new_table)
        if not existing:
            conn.execute(text(f"""
                ALTER TABLE score_data
                ADD CONSTRAINT score_data_application_id_fkey
                FOREIGN KEY (application_id) REFERENCES {new_table}(id) ON DELETE CASCADE
            """))
            print("    + score_data_application_id_fkey")
        else:
            print(f"    - score_data: 已存在 ({existing[0]})")

        # ---------- Step 6: 重命名索引 ----------
        print("\n[Step 6] 重命名索引...")
        index_renames = [
            ("idx_application_user_template_status", "idx_applications_user_template_status"),
            ("idx_application_status", "idx_applications_status"),
            ("idx_application_category", "idx_applications_category"),
        ]
        for old_idx, new_idx in index_renames:
            try:
                conn.execute(text(f'ALTER INDEX {old_idx} RENAME TO {new_idx}'))
                print(f"    ✓ {old_idx} → {new_idx}")
            except Exception as e:
                print(f"    - {old_idx}: {e}")

        # ---------- Step 7: 更新序列所有权 ----------
        print("\n[Step 7] 更新序列所有权...")
        result = conn.execute(text(f"""
            SELECT s.relname FROM pg_class s
            JOIN pg_depend d ON d.objid = s.oid
            WHERE d.refobjid = '{new_table}'::regclass
              AND s.relkind = 'S'
        """))
        seq_rows = result.fetchall()
        if seq_rows:
            seq_name = seq_rows[0][0]
            conn.execute(text(f'ALTER SEQUENCE {seq_name} OWNED BY {new_table}.id'))
            print(f"    ✓ {seq_name} 所有权已更新")
        else:
            print("    - 未找到序列，跳过")

    print("\n" + "=" * 70)
    print("迁移 015 完成！")
    print("=" * 70)
    print("\n验证:")
    print("  SELECT * FROM applications LIMIT 1;")
    print("  SELECT approved_count FROM applications LIMIT 1;")
    print("  然后重启 idpython 服务")


if __name__ == "__main__":
    migrate()
