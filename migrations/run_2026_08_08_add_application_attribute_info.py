"""
Run migration: applications 表增加 attribute_info JSONB 字段（v6 新增）

功能：
  - applications.attribute_info：申请提交时的 attribute 快照
  - 格式：{attribute.name: 用户填的值}
  - 默认 '{}'，对存量数据零侵入
  - 配套 GIN 索引，支持后续按 attribute_info 内容查询

用法：
  cd idbackend
  python -m migrations.run_2026_08_08_add_application_attribute_info [--dry-run]
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from src.infra.database import sync_engine


def run_migration(dry_run: bool = False) -> None:
    """执行 migration"""

    sql_add_column = """
    ALTER TABLE applications
      ADD COLUMN IF NOT EXISTS attribute_info JSONB NOT NULL DEFAULT '{}'::jsonb;
    """

    sql_comment = """
    COMMENT ON COLUMN applications.attribute_info IS
      '申请提交时的 attribute 快照：{attribute.name: 用户填的值}。提交时校验一次后完全独立，不依赖 attribute 表的当前状态。';
    """

    sql_create_index = """
    CREATE INDEX IF NOT EXISTS idx_applications_attribute_info_gin
      ON applications USING GIN (attribute_info);
    """

    with sync_engine.begin() as conn:
        # 1. 检查字段是否已存在（PostgreSQL：information_schema.columns）
        result = conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'applications' AND column_name = 'attribute_info'
        """))
        if result.fetchone():
            print("[SKIP] attribute_info 字段已存在，跳过")
        else:
            print(f"[SQL] {sql_add_column.strip()}")
            if not dry_run:
                conn.execute(text(sql_add_column))
                conn.execute(text(sql_comment))
                print("[OK] attribute_info 字段已添加")
            else:
                print("[DRY-RUN] 未实际执行 add column")

        # 2. 检查 GIN 索引是否存在（pg_indexes）
        result = conn.execute(text("""
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'applications' AND indexname = 'idx_applications_attribute_info_gin'
        """))
        if result.fetchone():
            print("[SKIP] idx_applications_attribute_info_gin 索引已存在，跳过")
        else:
            print(f"[SQL] {sql_create_index.strip()}")
            if not dry_run:
                conn.execute(text(sql_create_index))
                print("[OK] idx_applications_attribute_info_gin 索引已创建")
            else:
                print("[DRY-RUN] 未实际执行 create index")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("[DRY-RUN 模式]")
    run_migration(dry_run=dry_run)
