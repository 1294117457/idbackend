"""
Run migration: extra_info_field 表插入导出表所需的 5 条 NUMBER 字段

功能：
  - CET4成绩、NUMBER、sort_order=100
  - CET6成绩、NUMBER、sort_order=101
  - 专业成绩、NUMBER、sort_order=102
  - 排名    、NUMBER、sort_order=103
  - 排名人数、NUMBER、sort_order=104

这些字段会出现在学生「个人中心」扩展信息 card 中，
也用于 daily.md 238-239 导出表的 CET4 / CET6 / 专业成绩 / 排名 / 排名人数 列。

用法：
  cd idbackend
  python -m migrations.run_2026_08_08_add_export_extra_info_fields [--dry-run]
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from src.infra.database import sync_engine


# (name, type, sort_order, description)
FIELDS_TO_INSERT = [
    ("CET4成绩", "NUMBER", 100, "英语四级成绩"),
    ("CET6成绩", "NUMBER", 101, "英语六级成绩"),
    ("专业成绩", "NUMBER", 102, "学业综合 / 专业成绩"),
    ("排名",     "NUMBER", 103, "专业排名"),
    ("排名人数", "NUMBER", 104, "排名总人数"),
]


def _field_exists(conn, name: str) -> bool:
    """检查 extra_info_field 是否已有同名字段"""
    result = conn.execute(
        text("SELECT id FROM extra_info_field WHERE name = :name"),
        {"name": name},
    )
    return result.fetchone() is not None


def run_migration(dry_run: bool = False) -> None:
    """执行 migration"""

    sql_insert = """
        INSERT INTO extra_info_field
          (name, type, options, is_active, sort_order, description, created_at, updated_at)
        VALUES
          (:name, :type, '[]'::jsonb, true, :sort_order, :description, NOW(), NOW())
    """

    with sync_engine.begin() as conn:
        for name, ftype, sort_order, description in FIELDS_TO_INSERT:
            if _field_exists(conn, name):
                print(f"[SKIP] extra_info_field.name='{name}' 已存在，跳过")
                continue

            print(
                f"[SQL] INSERT extra_info_field "
                f"({name=}, {ftype=}, {sort_order=})"
            )
            if not dry_run:
                conn.execute(
                    text(sql_insert),
                    {
                        "name": name,
                        "type": ftype,
                        "sort_order": sort_order,
                        "description": description,
                    },
                )
                print(f"[OK] extra_info_field '{name}' 已插入")
            else:
                print("[DRY-RUN] 未实际执行 insert")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("[DRY-RUN 模式]")
    run_migration(dry_run=dry_run)
