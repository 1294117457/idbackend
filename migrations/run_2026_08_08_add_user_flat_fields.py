"""
Run migration: users 表增加导出表扁平字段（daily.md 238-239）

功能：
  - users.department       ：所在系
  - users.student_id       ：学号（自填；为空时 fallback 到 extract_student_id(username)）
  - users.gender           ：性别（M / F / OTHER）
  - users.id_card_number   ：身份证号
  - idx_users_student_id   ：学号索引（导出时按学号查询）

用法：
  cd idbackend
  python -m migrations.run_2026_08_08_add_user_flat_fields [--dry-run]
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from src.infra.database import sync_engine


def _column_exists(conn, table: str, column: str) -> bool:
    """检查字段是否存在"""
    result = conn.execute(
        text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = :table AND column_name = :column
        """),
        {"table": table, "column": column},
    )
    return result.fetchone() is not None


def _index_exists(conn, index_name: str) -> bool:
    """检查索引是否存在"""
    result = conn.execute(
        text("""
            SELECT indexname
            FROM pg_indexes
            WHERE indexname = :index_name
        """),
        {"index_name": index_name},
    )
    return result.fetchone() is not None


# ===================== SQL 片段 =====================

SQL_ADD_DEPARTMENT = """
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS department VARCHAR(100);
"""
COMMENT_DEPARTMENT = "COMMENT ON COLUMN users.department IS '所在系（学生自填，导出 daily.md 用）';"

SQL_ADD_STUDENT_ID = """
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS student_id VARCHAR(50);
"""
COMMENT_STUDENT_ID = (
    "COMMENT ON COLUMN users.student_id IS "
    "'学号（学生自填；为空时 fallback 到 extract_student_id(username)）';"
)
SQL_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_users_student_id
  ON users (student_id);
"""

SQL_ADD_GENDER = """
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS gender VARCHAR(10);
"""
COMMENT_GENDER = "COMMENT ON COLUMN users.gender IS '性别：M（男）/ F（女）/ OTHER（其他）';"

SQL_ADD_ID_CARD = """
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS id_card_number VARCHAR(18);
"""
COMMENT_ID_CARD = "COMMENT ON COLUMN users.id_card_number IS '身份证号（敏感信息，UI 不展示）';"


# ===================== 单步执行 =====================

def _run_step(
    conn,
    *,
    label: str,
    table: str,
    column: str,
    sql: str,
    comment_sql: str,
    dry_run: bool,
) -> None:
    if _column_exists(conn, table, column):
        print(f"[SKIP] {table}.{column} 字段已存在，跳过")
        return

    print(f"[SQL] {sql.strip()}")
    if not dry_run:
        conn.execute(text(sql))
        conn.execute(text(comment_sql))
        print(f"[OK] {table}.{column} 字段已添加")
    else:
        print("[DRY-RUN] 未实际执行 add column")


def _run_index_step(
    conn,
    *,
    index_name: str,
    sql: str,
    dry_run: bool,
) -> None:
    if _index_exists(conn, index_name):
        print(f"[SKIP] {index_name} 索引已存在，跳过")
        return

    print(f"[SQL] {sql.strip()}")
    if not dry_run:
        conn.execute(text(sql))
        print(f"[OK] {index_name} 索引已创建")
    else:
        print("[DRY-RUN] 未实际执行 create index")


# ===================== 主流程 =====================

def run_migration(dry_run: bool = False) -> None:
    """执行 migration"""

    with sync_engine.begin() as conn:
        # 1. department
        _run_step(
            conn,
            label="department",
            table="users",
            column="department",
            sql=SQL_ADD_DEPARTMENT,
            comment_sql=COMMENT_DEPARTMENT,
            dry_run=dry_run,
        )

        # 2. student_id
        _run_step(
            conn,
            label="student_id",
            table="users",
            column="student_id",
            sql=SQL_ADD_STUDENT_ID,
            comment_sql=COMMENT_STUDENT_ID,
            dry_run=dry_run,
        )
        # student_id 索引（导出时按学号查询）
        _run_index_step(
            conn,
            index_name="idx_users_student_id",
            sql=SQL_CREATE_INDEX,
            dry_run=dry_run,
        )

        # 3. gender
        _run_step(
            conn,
            label="gender",
            table="users",
            column="gender",
            sql=SQL_ADD_GENDER,
            comment_sql=COMMENT_GENDER,
            dry_run=dry_run,
        )

        # 4. id_card_number
        _run_step(
            conn,
            label="id_card_number",
            table="users",
            column="id_card_number",
            sql=SQL_ADD_ID_CARD,
            comment_sql=COMMENT_ID_CARD,
            dry_run=dry_run,
        )


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("[DRY-RUN 模式]")
    run_migration(dry_run=dry_run)
