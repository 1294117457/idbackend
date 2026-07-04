"""迁移脚本：删除 file_metadata.bucket_name 列

背景：
- bucket_name 是配置项（一个进程只对应一个 bucket），不应作为业务字段入 DB
- SeaweedFS 时代遗留此列，切换到 MinIO 后未清理
- 全代码库无任何读取该列的逻辑（已验证：grep 全文无 SELECT bucket_name）
- docs/core-function/file.md 第 222 行明确列为待删除 TODO

执行：python migrations/007_drop_file_metadata_bucket_name.py
回滚：python migrations/007_drop_file_metadata_bucket_name.py --rollback
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
    print("开始迁移：删除 file_metadata.bucket_name ...")

    with sync_engine.connect() as conn:
        if not column_exists(conn, "file_metadata", "bucket_name"):
            print("  ✓ bucket_name 列已不存在，无需迁移")
            return True

        print("  - 删除列: file_metadata.bucket_name")
        conn.execute(text("ALTER TABLE file_metadata DROP COLUMN bucket_name"))
        conn.commit()

        if column_exists(conn, "file_metadata", "bucket_name"):
            raise RuntimeError("迁移后仍存在 bucket_name 列，请人工检查")

    print("=" * 50)
    print("迁移完成！")
    print("=" * 50)
    print("\n后续步骤：")
    print("  1. ORM 模型（src/models/file.py）原本就没有 bucket_name，无需改")
    print("  2. 重启 idpython 服务")
    print("  3. 冒烟测试：上传 + 查询 + 下载")
    return True


def rollback():
    print("回滚：恢复 file_metadata.bucket_name 列 ...")

    with sync_engine.connect() as conn:
        if column_exists(conn, "file_metadata", "bucket_name"):
            print("  ✓ bucket_name 已存在，无需回滚")
            return True

        print("  + 添加列: file_metadata.bucket_name (NOT NULL, DEFAULT 'idproject')")
        # 回滚必须给 NOT NULL 一个 default，否则历史行会全部 UPDATE 失败
        conn.execute(text("""
            ALTER TABLE file_metadata
            ADD COLUMN bucket_name VARCHAR(100) NOT NULL DEFAULT 'idproject'
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