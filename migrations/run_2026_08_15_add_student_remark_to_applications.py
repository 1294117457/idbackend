"""
Run migration: applications 表增加 student_remark 字段
Usage: python -m migrations.run_2026_08_15_add_student_remark_to_applications [--dry-run]
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from src.infra.database import sync_engine


def run_migration(dry_run: bool = False) -> None:
    """执行 migration：applications 表增加 student_remark 字段（VARCHAR(500)，可空）"""

    sql = """
    ALTER TABLE applications
      ADD COLUMN IF NOT EXISTS student_remark VARCHAR(500);
    """

    comment_sql = """
    COMMENT ON COLUMN applications.student_remark IS
      '学生备注（v1）：学生在提交申请时录入的说明性文本，选填，≤500 字符。'
      '申请快照属性，与 rule_info 平级，不进入 operation_log。';
    """

    with sync_engine.begin() as conn:
        # 幂等检查：column 是否已存在
        result = conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'applications' AND column_name = 'student_remark'
        """))
        if result.fetchone():
            print("[SKIP] student_remark 字段已存在，跳过")
            return

        print(f"[SQL] {sql.strip()}")
        if not dry_run:
            conn.execute(text(sql))
            conn.execute(text(comment_sql))
            print("[OK] migration 执行成功")
        else:
            print("[DRY-RUN] 未实际执行")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("[DRY-RUN 模式]")
    run_migration(dry_run=dry_run)
