"""
Run migration: application_proofs 表增加 is_adjusted 字段
Usage: python -m migrations.run_2026_07_20_add_is_adjusted [--dry-run]
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from src.infra.database import sync_engine


def run_migration(dry_run: bool = False) -> None:
    """执行 migration"""

    sql = """
    ALTER TABLE application_proofs ADD COLUMN is_adjusted BOOLEAN NOT NULL DEFAULT false;
    """

    with sync_engine.begin() as conn:
        # 检查字段是否已存在
        result = conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'application_proofs' AND column_name = 'is_adjusted'
        """))
        if result.fetchone():
            print("[SKIP] is_adjusted 字段已存在，跳过")
            return

        print(f"[SQL] {sql.strip()}")
        if not dry_run:
            conn.execute(text(sql))
            conn.execute(text("""
                COMMENT ON COLUMN application_proofs.is_adjusted IS '是否被老师修正过：false=学生申报分，true=老师修正过的分';
            """))
            print("[OK] migration 执行成功")
        else:
            print("[DRY-RUN] 未实际执行")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("[DRY-RUN 模式]")
    run_migration(dry_run=dry_run)
