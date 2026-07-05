"""迁移脚本 (014)：application v4.2 设计落库

本迁移把 application / application_proofs / application 表结构对齐 v4.2 spec：

═══════════════════════════════════════════════════════════════════════
变更清单
═══════════════════════════════════════════════════════════════════════
Step 1: users 表新增 score_info / extra_info JSONB 字段（recalculate 快照 + 备用扩展）
Step 2: score_applications 表字段重构
  - status 改 VARCHAR(20) 6 态枚举（DRAFT/APPLYING/PASSED/REJECTED/WITHDRAWN/DISCARDED）
  - 删 student_id / student_name / major / enrollment_year / score_type
  - 删 apply_input / proofs_input / current_review_count / reviewer_ids / review_records / remark
  - 加 template_id NOT NULL（指向 template）
  - 加 category_id（指向 template_category）
  - 加 rejected_count DEFAULT 0
  - apply_score / gain_score 改 DECIMAL(5,2)
Step 3: application_proofs 表字段简化
  - proof_value → proof_score，类型 DECIMAL(5,2)
  - proof_file_id → file_id，改 nullable
  - status 改 VARCHAR(20) 3 态枚举（PENDING/APPROVED/REJECTED）
  - 删 review_count / approved_count / reviewer_ids / review_records / remark
Step 4: 新建 application_operation 表（操作审计日志）
Step 5: 新建 score_data 表（流水记录，recalculate 输入）

执行：python migrations/014_application_v42.py
回滚：python migrations/014_application_v42.py --rollback

═══════════════════════════════════════════════════════════════════════
前提：013 已执行（v3 旧表已 DROP），012 已执行（v4 template/rule/attribute 已建）
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


def safe_drop_column(conn, table: str, column: str) -> None:
    """DROP COLUMN IF EXISTS — 容错"""
    if column_exists(conn, table, column):
        conn.execute(text(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column} CASCADE"))
        print(f"    - DROP COLUMN {table}.{column}")


def safe_rename_column(conn, table: str, old: str, new: str) -> None:
    if column_exists(conn, table, old) and not column_exists(conn, table, new):
        conn.execute(text(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}"))
        print(f"    - RENAME {table}.{old} → {new}")


def safe_add_column(conn, table: str, column_def: str) -> None:
    """ADD COLUMN IF NOT EXISTS — 简单幂等"""
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column_def}"))


# ============================================================
# 正向迁移
# ============================================================
def migrate():
    print("=" * 70)
    print("迁移 014：application v4.2 设计落库")
    print("=" * 70)

    with sync_engine.begin() as conn:
        # ---------- Step 1: users 表新增字段 ----------
        print("\n[Step 1] users 表新增 score_info / extra_info...")
        safe_add_column(conn, "users", "score_info JSONB DEFAULT '{}'::jsonb")
        safe_add_column(conn, "users", "extra_info JSONB DEFAULT '{}'::jsonb")

        # ---------- Step 2: score_applications 表字段重构 ----------
        print("\n[Step 2] score_applications 表字段重构...")
        # 2.1 删旧字段
        for col in ("student_id", "student_name", "major", "enrollment_year",
                    "score_type", "apply_input", "proofs_input",
                    "current_review_count", "reviewer_ids",
                    "review_records", "remark"):
            safe_drop_column(conn, "score_applications", col)

        # 2.2 改 status 类型（int → varchar 6 态枚举）
        # 先看当前类型
        status_type = conn.execute(text("""
            SELECT data_type FROM information_schema.columns
            WHERE table_schema='public' AND table_name='score_applications' AND column_name='status'
        """)).scalar()
        if status_type and status_type != "character varying":
            print(f"    - ALTER status: {status_type} → VARCHAR(20) 6 态")
            conn.execute(text("""
                ALTER TABLE score_applications ALTER COLUMN status TYPE VARCHAR(20) USING
                    CASE status
                        WHEN '0' THEN 'APPLYING'
                        WHEN '1' THEN 'PASSED'
                        WHEN '2' THEN 'REJECTED'
                        WHEN '3' THEN 'WITHDRAWN'
                        WHEN '4' THEN 'REJECTED'
                        WHEN 0 THEN 'APPLYING'
                        WHEN 1 THEN 'PASSED'
                        WHEN 2 THEN 'REJECTED'
                        WHEN 3 THEN 'WITHDRAWN'
                        WHEN 4 THEN 'REJECTED'
                        ELSE 'APPLYING'
                    END
            """))
        if not constraint_exists(conn, "score_applications", "ck_application_status"):
            conn.execute(text("""
                ALTER TABLE score_applications
                ADD CONSTRAINT ck_application_status
                CHECK (status IN ('DRAFT','APPLYING','PASSED','REJECTED','WITHDRAWN','DISCARDED'))
            """))
            print("    + CHECK constraint ck_application_status")

        # 2.3 改分数类型
        for col, sql_type in (("apply_score", "DECIMAL(5,2)"),
                               ("gain_score", "DECIMAL(5,2)")):
            cur_type = conn.execute(text("""
                SELECT data_type FROM information_schema.columns
                WHERE table_schema='public' AND table_name='score_applications' AND column_name=:c
            """), {"c": col}).scalar()
            if cur_type and cur_type != "numeric":
                conn.execute(text(f"ALTER TABLE score_applications ALTER COLUMN {col} TYPE {sql_type} USING {col}::{sql_type}"))
                print(f"    - ALTER {col}: {cur_type} → {sql_type}")
            elif cur_type is None:
                conn.execute(text(f"ALTER TABLE score_applications ADD COLUMN {col} {sql_type} DEFAULT 0 NOT NULL"))
                print(f"    + ADD COLUMN {col} {sql_type}")

        # 2.4 加字段
        # template_id（必填）
        if not column_exists(conn, "score_applications", "template_id"):
            print("    + ADD COLUMN template_id INTEGER REFERENCES template(id)")
            conn.execute(text("""
                ALTER TABLE score_applications
                ADD COLUMN template_id INTEGER REFERENCES template(id)
            """))
            # 数据迁移占位：把现有 NULL 的填为 1
            conn.execute(text("UPDATE score_applications SET template_id = 1 WHERE template_id IS NULL"))
            conn.execute(text("ALTER TABLE score_applications ALTER COLUMN template_id SET NOT NULL"))

        # category_id（可空 → 迁移期允许 NULL，业务上线后 NOT NULL）
        if not column_exists(conn, "score_applications", "category_id"):
            print("    + ADD COLUMN category_id INTEGER REFERENCES template_category(id)")
            conn.execute(text("""
                ALTER TABLE score_applications
                ADD COLUMN category_id INTEGER REFERENCES template_category(id)
            """))

        # rejected_count
        if not column_exists(conn, "score_applications", "rejected_count"):
            print("    + ADD COLUMN rejected_count INTEGER DEFAULT 0")
            safe_add_column(conn, "score_applications", "rejected_count INTEGER DEFAULT 0")

        # 2.5 索引
        if not index_exists(conn, "idx_application_user_template_status"):
            conn.execute(text("""
                CREATE INDEX idx_application_user_template_status
                ON score_applications (user_id, template_id, status)
            """))
            print("    + INDEX idx_application_user_template_status")
        if not index_exists(conn, "idx_application_status"):
            conn.execute(text("""
                CREATE INDEX idx_application_status
                ON score_applications (status)
            """))
            print("    + INDEX idx_application_status")
        if not index_exists(conn, "idx_application_category"):
            conn.execute(text("""
                CREATE INDEX idx_application_category
                ON score_applications (category_id)
            """))
            print("    + INDEX idx_application_category")

        # ---------- Step 3: application_proofs 表字段简化 ----------
        print("\n[Step 3] application_proofs 表字段简化...")
        # 3.1 proof_value → proof_score
        safe_rename_column(conn, "application_proofs", "proof_value", "proof_score")
        # 改 proof_score 类型
        proof_score_type = conn.execute(text("""
            SELECT data_type FROM information_schema.columns
            WHERE table_schema='public' AND table_name='application_proofs' AND column_name='proof_score'
        """)).scalar()
        if proof_score_type and proof_score_type != "numeric":
            conn.execute(text("ALTER TABLE application_proofs ALTER COLUMN proof_score TYPE DECIMAL(5,2) USING proof_score::DECIMAL(5,2)"))
            print(f"    - ALTER proof_score: {proof_score_type} → DECIMAL(5,2)")

        # 3.2 proof_file_id → file_id
        safe_rename_column(conn, "application_proofs", "proof_file_id", "file_id")
        # 改 file_id nullable
        file_id_nullable = conn.execute(text("""
            SELECT is_nullable FROM information_schema.columns
            WHERE table_schema='public' AND table_name='application_proofs' AND column_name='file_id'
        """)).scalar()
        if file_id_nullable == "NO":
            conn.execute(text("ALTER TABLE application_proofs ALTER COLUMN file_id DROP NOT NULL"))
            print("    - file_id → nullable")

        # 3.3 改 status 类型
        proof_status_type = conn.execute(text("""
            SELECT data_type FROM information_schema.columns
            WHERE table_schema='public' AND table_name='application_proofs' AND column_name='status'
        """)).scalar()
        if proof_status_type and proof_status_type != "character varying":
            print(f"    - ALTER proof.status: {proof_status_type} → VARCHAR(20) 3 态")
            conn.execute(text("""
                ALTER TABLE application_proofs ALTER COLUMN status TYPE VARCHAR(20) USING
                    CASE status
                        WHEN '0' THEN 'PENDING'
                        WHEN '1' THEN 'APPROVED'
                        WHEN '2' THEN 'REJECTED'
                        WHEN 0 THEN 'PENDING'
                        WHEN 1 THEN 'APPROVED'
                        WHEN 2 THEN 'REJECTED'
                        ELSE 'PENDING'
                    END
            """))
        if not constraint_exists(conn, "application_proofs", "ck_proof_status"):
            conn.execute(text("""
                ALTER TABLE application_proofs
                ADD CONSTRAINT ck_proof_status
                CHECK (status IN ('PENDING','APPROVED','REJECTED'))
            """))
            print("    + CHECK constraint ck_proof_status")

        # 3.4 删冗余字段
        for col in ("review_count", "approved_count", "reviewer_ids",
                    "review_records", "remark"):
            safe_drop_column(conn, "application_proofs", col)

        # 3.5 索引
        if not index_exists(conn, "idx_proofs_application"):
            conn.execute(text("CREATE INDEX idx_proofs_application ON application_proofs (application_id)"))
            print("    + INDEX idx_proofs_application")
        if not index_exists(conn, "idx_proofs_application_status"):
            conn.execute(text("CREATE INDEX idx_proofs_application_status ON application_proofs (application_id, status)"))
            print("    + INDEX idx_proofs_application_status")

        # ---------- Step 4: 新建 application_operation 表 ----------
        print("\n[Step 4] 新建 application_operation 表...")
        if not table_exists(conn, "application_operation"):
            conn.execute(text("""
                CREATE TABLE application_operation (
                    id              SERIAL PRIMARY KEY,
                    application_id  INTEGER NOT NULL REFERENCES score_applications(id) ON DELETE CASCADE,
                    operator_id     INTEGER NOT NULL,
                    operator_name   VARCHAR(100) NOT NULL,
                    operation       VARCHAR(30) NOT NULL,
                    remark          TEXT,
                    created_at      TIMESTAMP DEFAULT NOW(),
                    updated_at      TIMESTAMP DEFAULT NOW(),
                    CONSTRAINT ck_application_operation_type
                        CHECK (operation IN (
                            'CREATE_DRAFT','UPDATE_DRAFT','DISCARD_DRAFT',
                            'SUBMIT','PASS','REJECT','RESUBMIT','WITHDRAW','REVOKE'
                        ))
                )
            """))
            conn.execute(text("CREATE INDEX idx_operation_application ON application_operation (application_id)"))
            conn.execute(text("CREATE INDEX idx_operation_app_op ON application_operation (application_id, operation)"))
            print("    + CREATE TABLE application_operation")
        else:
            print("    ✓ application_operation 已存在")

        # ---------- Step 5: 新建 score_data 表 ----------
        print("\n[Step 5] 新建 score_data 表...")
        if not table_exists(conn, "score_data"):
            conn.execute(text("""
                CREATE TABLE score_data (
                    id              SERIAL PRIMARY KEY,
                    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    application_id  INTEGER NOT NULL REFERENCES score_applications(id) ON DELETE CASCADE,
                    category_id     INTEGER NOT NULL REFERENCES template_category(id),
                    name            VARCHAR(100),
                    score           DECIMAL(5, 2) NOT NULL,
                    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at      TIMESTAMP DEFAULT NOW(),
                    updated_at      TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text("CREATE INDEX idx_score_data_user_active ON score_data (user_id, is_active)"))
            conn.execute(text("CREATE INDEX idx_score_data_user_category ON score_data (user_id, category_id)"))
            conn.execute(text("CREATE INDEX idx_score_data_application ON score_data (application_id)"))
            print("    + CREATE TABLE score_data")
        else:
            print("    ✓ score_data 已存在")

    print("\n" + "=" * 70)
    print("迁移 014 完成！")
    print("=" * 70)
    print("\n下一步：")
    print("  1. 重启 idpython 服务（让 ORM 加载新表映射）")
    print("  2. 跑 application_service 的测试验证")
    return True


# ============================================================
# 回滚
# ============================================================
def rollback():
    print("回滚 014：撤销 application v4.2 设计...")

    with sync_engine.begin() as conn:
        # Step 5 反向：删 score_data
        if table_exists(conn, "score_data"):
            print("  - DROP TABLE score_data CASCADE")
            conn.execute(text("DROP TABLE score_data CASCADE"))

        # Step 4 反向：删 application_operation
        if table_exists(conn, "application_operation"):
            print("  - DROP TABLE application_operation CASCADE")
            conn.execute(text("DROP TABLE application_operation CASCADE"))

        # Step 3 反向：删 proof 表冗余字段 + 改回旧名
        for col in ("review_count", "approved_count", "reviewer_ids",
                    "review_records", "remark"):
            if column_exists(conn, "application_proofs", col):
                conn.execute(text(f"ALTER TABLE application_proofs DROP COLUMN {col}"))

        if column_exists(conn, "application_proofs", "file_id"):
            conn.execute(text("ALTER TABLE application_proofs RENAME COLUMN file_id TO proof_file_id"))
            conn.execute(text("ALTER TABLE application_proofs ALTER COLUMN proof_file_id SET NOT NULL"))

        if column_exists(conn, "application_proofs", "proof_score"):
            conn.execute(text("ALTER TABLE application_proofs RENAME COLUMN proof_score TO proof_value"))

        conn.execute(text("""
            ALTER TABLE application_proofs
            ALTER COLUMN status TYPE INTEGER USING
                CASE status WHEN 'PENDING' THEN 0 WHEN 'APPROVED' THEN 1 WHEN 'REJECTED' THEN 2 ELSE 0 END
        """))

        # Step 2 反向：恢复 application 字段
        if not column_exists(conn, "score_applications", "student_id"):
            conn.execute(text("ALTER TABLE score_applications ADD COLUMN student_id VARCHAR(50)"))
        if not column_exists(conn, "score_applications", "student_name"):
            conn.execute(text("ALTER TABLE score_applications ADD COLUMN student_name VARCHAR(100)"))
        if not column_exists(conn, "score_applications", "major"):
            conn.execute(text("ALTER TABLE score_applications ADD COLUMN major VARCHAR(100)"))
        if not column_exists(conn, "score_applications", "enrollment_year"):
            conn.execute(text("ALTER TABLE score_applications ADD COLUMN enrollment_year INTEGER"))
        if not column_exists(conn, "score_applications", "score_type"):
            conn.execute(text("ALTER TABLE score_applications ADD COLUMN score_type INTEGER DEFAULT 0"))
        if not column_exists(conn, "score_applications", "apply_input"):
            conn.execute(text("ALTER TABLE score_applications ADD COLUMN apply_input INTEGER"))
        if not column_exists(conn, "score_applications", "current_review_count"):
            conn.execute(text("ALTER TABLE score_applications ADD COLUMN current_review_count INTEGER DEFAULT 0"))
        if not column_exists(conn, "score_applications", "reviewer_ids"):
            conn.execute(text("ALTER TABLE score_applications ADD COLUMN reviewer_ids JSONB"))
        if not column_exists(conn, "score_applications", "review_records"):
            conn.execute(text("ALTER TABLE score_applications ADD COLUMN review_records JSONB"))
        if not column_exists(conn, "score_applications", "remark"):
            conn.execute(text("ALTER TABLE score_applications ADD COLUMN remark TEXT"))

        conn.execute(text("""
            ALTER TABLE score_applications
            ALTER COLUMN status TYPE INTEGER USING
                CASE status
                    WHEN 'APPLYING' THEN 0
                    WHEN 'PASSED' THEN 1
                    WHEN 'REJECTED' THEN 2
                    WHEN 'WITHDRAWN' THEN 3
                    WHEN 'DRAFT' THEN 0
                    WHEN 'DISCARDED' THEN 4
                    ELSE 0
                END
        """))

        # Step 1 反向：删 users 字段
        for col in ("score_info", "extra_info"):
            if column_exists(conn, "users", col):
                conn.execute(text(f"ALTER TABLE users DROP COLUMN {col}"))

    print("=" * 50)
    print("回滚 014 完成")
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