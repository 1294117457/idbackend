"""
数据库迁移脚本（幂等）

添加 applications.reviewer_ids JSON 字段（v4.3）

使用方法（任选一种）：
  1. Python: python -m src.scripts.migrate_add_reviewer_ids
  2. SQL:    psql $DATABASE_URL -f src/scripts/migrate_add_reviewer_ids.sql
  3. 手动:   直接在数据库执行下方 SQL
"""
from sqlalchemy import text

from src.infra.database import get_sync_db


def run_migration():
    with get_sync_db() as db:
        # 检查列是否存在
        result = db.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'applications' AND column_name = 'reviewer_ids'
        """))
        if result.fetchone():
            print("[OK] reviewer_ids 列已存在，跳过")
            return

        # 添加列（PostgreSQL JSON 类型，default []）
        db.execute(text("""
            ALTER TABLE applications
            ADD COLUMN reviewer_ids JSONB DEFAULT '[]'::JSONB
            NOT NULL
        """))
        # 加索引（审核员分流查询高频）
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_applications_reviewer_ids
            ON applications USING GIN (reviewer_ids)
        """))
        db.commit()
        print("[OK] reviewer_ids 列 + GIN 索引创建成功")


if __name__ == "__main__":
    run_migration()
