"""
数据库迁移脚本（幂等）

添加 applications.reviewer_ids JSON 字段 + GIN 索引（v4.3）

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
        else:
            # 添加列（PostgreSQL JSON 类型，default []）
            db.execute(text("""
                ALTER TABLE applications
                ADD COLUMN reviewer_ids JSONB DEFAULT '[]'::JSONB
                NOT NULL
            """))
            db.commit()
            print("[OK] reviewer_ids 列创建成功")

        # 确保存在 jsonb_path_ops 的 GIN 索引（适合 ? / @> 等包含查询）
        # 先删可能存在的旧索引（用默认 jsonb_ops），再重建
        db.execute(text("""
            DROP INDEX IF EXISTS idx_applications_reviewer_ids
        """))
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_reviewers
            ON applications USING GIN (reviewer_ids jsonb_path_ops)
        """))
        db.commit()
        print("[OK] GIN 索引 idx_reviewers (jsonb_path_ops) 创建成功")


if __name__ == "__main__":
    run_migration()
