"""添加 is_deleted 字段到 template_category 表（软删除支持）

执行：python3 migrations/016_add_is_deleted_to_template_category.py
"""
import sys
sys.path.insert(0, ".")

from sqlalchemy import text
from src.infra.database import sync_engine


def main():
    with sync_engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE template_category
            ADD COLUMN is_deleted BOOLEAN NOT NULL DEFAULT FALSE
        """))
        print("OK: is_deleted column added")

        conn.execute(text("""
            CREATE INDEX idx_template_category_deleted
            ON template_category(is_deleted)
        """))
        print("OK: index created")

    print("\nDone!")


if __name__ == "__main__":
    main()
