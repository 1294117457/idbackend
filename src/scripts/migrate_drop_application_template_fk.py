"""数据库迁移脚本（幂等）

解耦 applications.template_id 与 template.id 的外键约束。

设计动机：
  application 主体已经把 template_name / category_id / apply_score
  同步为快照字段，业务路径（list / score 计算 / 审核）完全不 JOIN template。
  template 删除时不应影响 applications 表的任何行
  （既不能 CASCADE 删，也不能 SET NULL 把 template_id 改写成 NULL）。

实施内容：
  1. 移除 applications.template_id 的外键约束（applications_template_id_fkey）
  2. 删除已无人查询使用的 (user_id, template_id, status) 三列组合索引
     注：(user_id, status) 二列索引已在 migrate_add_query_indexes.sql 里建过

使用方法（任选一种）：
  1. Python: python -m src.scripts.migrate_drop_application_template_fk
  2. SQL:    psql $DATABASE_URL -f src/scripts/migrate_drop_application_template_fk.sql
  3. 手动:   在数据库直接执行下方 SQL
"""
from sqlalchemy import text

from src.infra.database import get_sync_db


def run_migration():
    with get_sync_db() as db:
        # ─── 前置检查：确认 FK 存在 ─────────────────────────────
        fk_row = db.execute(text("""
            SELECT conname
            FROM pg_constraint
            WHERE conrelid = 'applications'::regclass
              AND contype = 'f'
              AND conname = 'applications_template_id_fkey'
        """)).fetchone()

        idx_row = db.execute(text("""
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'applications'
              AND indexname = 'idx_application_user_template_status'
        """)).fetchone()

        if not fk_row and not idx_row:
            print("[OK] 目标约束与索引都已不存在，无需迁移")
            return

        # ─── 1. 移除 FK 约束 ─────────────────────────────
        if fk_row:
            print(f"[DROP] 移除 FK 约束 {fk_row[0]}")
            db.execute(text("""
                ALTER TABLE applications
                DROP CONSTRAINT applications_template_id_fkey
            """))
            db.commit()
            print("[OK] FK 约束已移除")
        else:
            print("[SKIP] FK 约束已不存在")

        # ─── 2. 删除冗余的三列组合索引 ─────────────────────
        if idx_row:
            print(f"[DROP] 删除冗余索引 {idx_row[0]}")
            db.execute(text("""
                DROP INDEX IF EXISTS idx_application_user_template_status
            """))
            db.commit()
            print("[OK] 冗余索引已删除")
        else:
            print("[SKIP] 冗余索引已不存在")

        # ─── 验证 ────────────────────────────────────────
        verify_fk = db.execute(text("""
            SELECT conname
            FROM pg_constraint
            WHERE conrelid = 'applications'::regclass
              AND contype = 'f'
              AND conname = 'applications_template_id_fkey'
        """)).fetchone()

        verify_idx = db.execute(text("""
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'applications'
              AND indexname = 'idx_application_user_template_status'
        """)).fetchone()

        if verify_fk or verify_idx:
            raise RuntimeError(
                f"迁移后验证失败：FK={verify_fk}, idx={verify_idx}"
            )

        print("[VERIFY] ✅ applications 表仅剩 user_id / template_category / "
              "其它 FK，applications_template_id_fkey 已彻底移除")
        print("[VERIFY] ✅ idx_application_user_template_status 已彻底删除")


if __name__ == "__main__":
    run_migration()
