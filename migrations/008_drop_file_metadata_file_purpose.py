"""迁移脚本：删除 file_metadata.file_purpose 列

背景：
- file_purpose 是已被废弃的业务字段，不应再保留
- 全代码库已无任何读取/写入该列的逻辑（已验证：grep 全文无引用）
- 删除后无业务影响（已上传文件的该字段值会被丢弃）

执行：python migrations/008_drop_file_metadata_file_purpose.py
回滚：python migrations/008_drop_file_metadata_file_purpose.py --rollback
"""
import sys
sys.path.insert(0, '.')

from sqlalchemy import text
from src.infra.database import sync_engine


def column_exists(conn, table: str, column: str) -> bool:
    row = conn.execute(text("""
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = :t AND column_name = :c
        LIMIT 1
    """), {"t": table, "c": column}).first()
    return row is not None


def migrate():
    print("开始迁移：删除 file_metadata.file_purpose ...")

    with sync_engine.connect() as conn:
        if not column_exists(conn, "file_metadata", "file_purpose"):
            print("  ✓ file_purpose 列已不存在，无需迁移")
            return True

        print("  - 删除列: file_metadata.file_purpose")
        conn.execute(text("ALTER TABLE file_metadata DROP COLUMN file_purpose"))
        conn.commit()

        if column_exists(conn, "file_metadata", "file_purpose"):
            raise RuntimeError("迁移后仍存在 file_purpose 列，请人工检查")

    print("=" * 50)
    print("迁移完成！")
    print("=" * 50)
    print("\n后续步骤：")
    print("  1. ORM 模型（src/models/file.py）原本就没有 file_purpose，无需改")
    print("  2. 重启 idpython 服务")
    print("  3. 冒烟测试：上传 + 查询 + 下载")
    return True


def rollback():
    print("回滚：恢复 file_metadata.file_purpose 列 ...")

    with sync_engine.connect() as conn:
        if column_exists(conn, "file_metadata", "file_purpose"):
            print("  ✓ file_purpose 已存在，无需回滚")
            return True

        print("  + 添加列: file_metadata.file_purpose (VARCHAR(200), NULL)")
        conn.execute(text("""
            ALTER TABLE file_metadata
            ADD COLUMN file_purpose VARCHAR(200)
        """))
        conn.commit()

    print("=" * 50)
    print("回滚完成！")
    print("=" * 50)
    return True


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--rollback', action='store_true', help='回滚迁移')
    args = parser.parse_args()

    if args.rollback:
        rollback()
    else:
        migrate()
