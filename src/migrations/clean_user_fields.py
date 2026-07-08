"""Migration: 清理 users 表无用字段

执行: python -m migrations.clean_user_fields

删除以下字段:
- gpa
- is_confirmed
- demand_value
- demand_files
- academic_score
- specialty_score
- comprehensive_score
- student_id

保留:
- username, password, phone, avatar, status, last_login_at
- full_name, grade, graduation_year, enrollment_year, major
- id, created_at, updated_at, score_info, extra_info
"""
from sqlalchemy import text
from src.infra.database import sync_engine


def upgrade():
    """删除无用字段"""
    with sync_engine.begin() as conn:
        # 删除不需要的字段
        conn.execute(text("""
            ALTER TABLE users
              DROP COLUMN IF EXISTS gpa,
              DROP COLUMN IF EXISTS is_confirmed,
              DROP COLUMN IF EXISTS demand_value,
              DROP COLUMN IF EXISTS demand_files,
              DROP COLUMN IF EXISTS academic_score,
              DROP COLUMN IF EXISTS specialty_score,
              DROP COLUMN IF EXISTS comprehensive_score,
              DROP COLUMN IF EXISTS student_id
        """))
        print("✅ users 表无用字段已删除")


def downgrade():
    """回滚（仅供参考，实际生产不建议回滚）"""
    with sync_engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE users
              ADD COLUMN IF NOT EXISTS gpa DOUBLE PRECISION,
              ADD COLUMN IF NOT EXISTS is_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
              ADD COLUMN IF NOT EXISTS demand_value JSON,
              ADD COLUMN IF NOT EXISTS demand_files JSON,
              ADD COLUMN IF NOT EXISTS academic_score DOUBLE PRECISION NOT NULL DEFAULT 0,
              ADD COLUMN IF NOT EXISTS specialty_score DOUBLE PRECISION NOT NULL DEFAULT 0,
              ADD COLUMN IF NOT EXISTS comprehensive_score DOUBLE PRECISION NOT NULL DEFAULT 0,
              ADD COLUMN IF NOT EXISTS student_id VARCHAR(50)
        """))
        print("✅ 回滚完成")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "downgrade":
        downgrade()
    else:
        upgrade()
