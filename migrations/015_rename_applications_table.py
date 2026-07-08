"""迁移脚本 (015)：表重命名 + 修复 approved_count 缺失

═══════════════════════════════════════════════════════════════════════
变更清单
═══════════════════════════════════════════════════════════════════════
1. 表重命名：score_applications → applications
2. 修复 approved_count 字段缺失问题
3. 更新外键引用：application_operation.application_id → applications
4. 更新外键引用：application_proofs.application_id → applications
5. 更新外键引用：score_data.application_id → applications

执行：python migrations/015_rename_applications_table.py
回滚：python migrations/015_rename_applications_table.py --rollback

═══════════════════════════════════════════════════════════════════════
"""
import sys
sys.path.insert(0, '.')

from sqlalchemy import text
from src.infra.database import sync_engine


# ============================================================
# 元数据查询
# ============================================================
def table_exists(conn, table_name: str) -> bool:
    row = conn.execute(text("""
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = :t LIMIT 1
    """), {"t": table_name}).first()
    return row is not None


def column_exists(conn, table: str, column: str) -> bool:
    row = conn.execute(text("""
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = :t AND column_name = :c LIMIT 1
    """), {"t": table, "c": column}).first()
    return row is not None


def constraint_exists(conn, table: str, name: str) -> bool:
    row = conn.execute(text("""
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_schema = 'public' AND table_name = :t AND constraint_name = :c LIMIT 1
    """), {"t": table, "c": name}).first()
    return row is not None


def index_exists(conn, name: str) -> bool:
    row = conn.execute(text("""
        SELECT 1 FROM pg_indexes
        WHERE schemaname = 'public' AND indexname = :i LIMIT 1
    """), {"i": name}).first()
    return row is not None


def get_foreign_key_constraints(conn, table: str) -> list:
    """获取表的外键约束"""
    result = conn.execute(text("""
        SELECT
            conname AS constraint_name,
            att.attname AS column_name,
            confrel.relname AS foreign_table_name,
            af.attname AS foreign_column_name
        FROM pg_catalog.pg_constraint AS con
        JOIN pg_catalog.pg_attribute AS att
            ON att.attrelid = con.conrelid AND att.attnum = ANY(con.conkey)
        JOIN pg_catalog.pg_class AS cl
            ON cl.oid = con.conrelid
        JOIN pg_catalog.pg_class AS confrel
            ON confrel.oid = con.confrelid
        JOIN pg_catalog.pg_attribute AS af
            ON af.attrelid = con.confrelid AND af.attnum = ANY(con.confkey)
        WHERE con.contype = 'f'
          AND cl.relname = :t
          AND con.connamespace = (
              SELECT oid FROM pg_namespace WHERE nspname = 'public'
          )
    """), {"t": table})
    return [(r[0], r[1], r[2], r[3]) for r in result]


def get_indexes(conn, table: str) -> list:
    """获取表的索引"""
    result = conn.execute(text("""
        SELECT indexname
        FROM pg_indexes
        WHERE schemaname = 'public' AND tablename = :t
    """), {"t": table})
    return [r[0] for r in result]


# ============================================================
# 正向迁移
# ============================================================
def migrate():
    print("=" * 70)
    print("迁移 015：表重命名 + 修复 approved_count")
    print("=" * 70)

    with sync_engine.begin() as conn:
        # ---------- Step 1: 检查旧表是否存在 ----------
        old_table = "score_applications"
        new_table = "applications"

        if not table_exists(conn, old_table):
            print(f"\n[ERROR] 旧表 {old_table} 不存在，请先执行迁移 014")
            return False

        if table_exists(conn, new_table):
            print(f"\n[WARN] 新表 {new_table} 已存在，跳过重命名")
        else:
            # ---------- Step 2: 重命名表 ----------
            print(f"\n[Step 1] 重命名表: {old_table} → {new_table}")
            conn.execute(text(f"ALTER TABLE {old_table} RENAME TO {new_table}"))
            print(f"    ✓ 表已重命名")

            # 重命名主键序列
            if table_exists(conn, f"{old_table}_id_seq"):
                conn.execute(text(f"ALTER TABLE {old_table}_id_seq RENAME TO {new_table}_id_seq"))
                print(f"    ✓ 序列已重命名: {old_table}_id_seq → {new_table}_id_seq")

            # 重命名主键约束
            old_pk = f"{old_table}_pkey"
            new_pk = f"{new_table}_pkey"
            if constraint_exists(conn, old_table, old_pk):
                conn.execute(text(f"ALTER TABLE {new_table} RENAME CONSTRAINT {old_pk} TO {new_pk}"))
                print(f"    ✓ 主键约束已重命名")

        # ---------- Step 3: 修复 approved_count 缺失 ----------
        print(f"\n[Step 2] 修复 approved_count 字段...")
        if not column_exists(conn, new_table, "approved_count"):
            conn.execute(text(f"""
                ALTER TABLE {new_table}
                ADD COLUMN approved_count INTEGER DEFAULT 0 NOT NULL
            """))
            print(f"    + ADD COLUMN approved_count INTEGER DEFAULT 0")
        else:
            print(f"    ✓ approved_count 已存在")

        # ---------- Step 4: 更新 application_operation 外键 ----------
        print(f"\n[Step 3] 更新 application_operation 外键...")
        op_fk_list = get_foreign_key_constraints(conn, "application_operation")
        for fk in op_fk_list:
            constraint_name = fk[0]
            if "score_applications" in constraint_name.lower():
                conn.execute(text(f"""
                    ALTER TABLE application_operation
                    DROP CONSTRAINT {constraint_name}
                """))
                print(f"    - DROP CONSTRAINT {constraint_name}")

        # 检查是否有新的外键（指向 applications）
        new_fk_exists = any(
            "applications" in str(fk).lower()
            for fk in get_foreign_key_constraints(conn, "application_operation")
        )
        if not new_fk_exists:
            conn.execute(text(f"""
                ALTER TABLE application_operation
                ADD CONSTRAINT application_operation_application_id_fkey
                FOREIGN KEY (application_id) REFERENCES {new_table}(id) ON DELETE CASCADE
            """))
            print(f"    + ADD CONSTRAINT application_operation_application_id_fkey")

        # ---------- Step 5: 更新 application_proofs 外键 ----------
        print(f"\n[Step 4] 更新 application_proofs 外键...")
        pf_fk_list = get_foreign_key_constraints(conn, "application_proofs")
        for fk in pf_fk_list:
            constraint_name = fk[0]
            if "score_applications" in constraint_name.lower():
                conn.execute(text(f"""
                    ALTER TABLE application_proofs
                    DROP CONSTRAINT {constraint_name}
                """))
                print(f"    - DROP CONSTRAINT {constraint_name}")

        new_fk_exists = any(
            "applications" in str(fk).lower()
            for fk in get_foreign_key_constraints(conn, "application_proofs")
        )
        if not new_fk_exists:
            conn.execute(text(f"""
                ALTER TABLE application_proofs
                ADD CONSTRAINT application_proofs_application_id_fkey
                FOREIGN KEY (application_id) REFERENCES {new_table}(id) ON DELETE CASCADE
            """))
            print(f"    + ADD CONSTRAINT application_proofs_application_id_fkey")

        # ---------- Step 6: 更新 score_data 外键 ----------
        print(f"\n[Step 5] 更新 score_data 外键...")
        sd_fk_list = get_foreign_key_constraints(conn, "score_data")
        for fk in sd_fk_list:
            constraint_name = fk[0]
            if "score_applications" in constraint_name.lower():
                conn.execute(text(f"""
                    ALTER TABLE score_data
                    DROP CONSTRAINT {constraint_name}
                """))
                print(f"    - DROP CONSTRAINT {constraint_name}")

        new_fk_exists = any(
            "applications" in str(fk).lower()
            for fk in get_foreign_key_constraints(conn, "score_data")
        )
        if not new_fk_exists:
            conn.execute(text(f"""
                ALTER TABLE score_data
                ADD CONSTRAINT score_data_application_id_fkey
                FOREIGN KEY (application_id) REFERENCES {new_table}(id) ON DELETE CASCADE
            """))
            print(f"    + ADD CONSTRAINT score_data_application_id_fkey")

        # ---------- Step 7: 重命名索引 ----------
        print(f"\n[Step 6] 重命名相关索引...")

        # 索引映射：旧名 → 新名
        index_renames = {
            "idx_application_user_template_status": "idx_applications_user_template_status",
            "idx_application_status": "idx_applications_status",
            "idx_application_category": "idx_applications_category",
            f"{old_table}_pkey": f"{new_table}_pkey",
        }

        for old_idx, new_idx in index_renames.items():
            if index_exists(conn, old_idx):
                conn.execute(text(f"ALTER INDEX {old_idx} RENAME TO {new_idx}"))
                print(f"    ✓ {old_idx} → {new_idx}")

        # 重建索引名称（如果是自动命名的）
        for idx in get_indexes(conn, new_table):
            if old_table in idx:
                new_idx = idx.replace(old_table, new_table)
                if not index_exists(conn, new_idx):
                    conn.execute(text(f"ALTER INDEX {idx} RENAME TO {new_idx}"))
                    print(f"    ✓ {idx} → {new_idx}")

        # ---------- Step 8: 更新 sequence ownership ----------
        print(f"\n[Step 7] 更新序列所有权...")
        conn.execute(text(f"""
            ALTER SEQUENCE {new_table}_id_seq
            OWNED BY {new_table}.id
        """))
        print(f"    ✓ 序列所有权已更新")

    print("\n" + "=" * 70)
    print("迁移 015 完成！")
    print("=" * 70)
    print("\n验证:")
    print("  1. SELECT * FROM applications LIMIT 1;")
    print("  2. SELECT approved_count FROM applications LIMIT 1;")
    print("  3. 重启 idpython 服务")
    return True


# ============================================================
# 回滚
# ============================================================
def rollback():
    print("回滚 015：撤销表重命名...")

    with sync_engine.begin() as conn:
        old_table = "score_applications"
        new_table = "applications"

        # 恢复 approved_count（不改，因为是新加的字段）

        # 重命名表回原名
        if table_exists(conn, new_table) and not table_exists(conn, old_table):
            conn.execute(text(f"ALTER TABLE {new_table} RENAME TO {old_table}"))
            print(f"  ✓ 表已重命名回: {old_table}")

            # 重命名序列
            if table_exists(conn, f"{new_table}_id_seq"):
                conn.execute(text(f"ALTER TABLE {new_table}_id_seq RENAME TO {old_table}_id_seq"))
                print(f"  ✓ 序列已重命名回")

        # 重命名索引
        index_renames = {
            "idx_applications_user_template_status": "idx_application_user_template_status",
            "idx_applications_status": "idx_application_status",
            "idx_applications_category": "idx_application_category",
            f"{new_table}_pkey": f"{old_table}_pkey",
        }

        for old_idx, new_idx in index_renames.items():
            if index_exists(conn, old_idx):
                conn.execute(text(f"ALTER INDEX {old_idx} RENAME TO {new_idx}"))
                print(f"  ✓ {old_idx} → {new_idx}")

    print("=" * 50)
    print("回滚 015 完成")
    print("=" * 50)
    return True


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--rollback', action='store_true')
    args = parser.parse_args()

    if args.rollback:
        rollback()
    else:
        migrate()
