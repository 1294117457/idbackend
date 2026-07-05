"""迁移脚本 (010)：将 score_templates 相关 FK 改为指向 template_category

背景（Layer 1 落地）：
- score_templates 当前通过 field_id / subcategory_id 整数关联到 FieldConfig / FieldSubcategory
- Layer 1 落地后改用 template_category 一棵树，统一管理分类与上限
- 本迁移脚本做了"对当前现状最小侵入"的修改：为 score_templates 新增 category_id 列，
  指向 template_category.id，ON DELETE CASCADE 行为与文档"分类被删时 template 一起删"一致
- 注：field_id / subcategory_id 暂保留（不破坏现状），后续在更大范围迁移（Layer 1 完整落地 + Layer 2 落地）中替换

执行：python migrations/010_add_template_category_id_to_score_templates.py
回滚：python migrations/010_add_template_category_id_to_score_templates.py --rollback
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


def constraint_exists(conn, table: str, constraint_name: str) -> bool:
    row = conn.execute(text("""
        SELECT 1
        FROM information_schema.table_constraints
        WHERE table_name = :t AND constraint_name = :c
        LIMIT 1
    """), {"t": table, "c": constraint_name}).first()
    return row is not None


def migrate():
    print("开始迁移：score_templates.category_id（指向 template_category）...")

    with sync_engine.connect() as conn:
        # 1. 添加 category_id 列
        if column_exists(conn, "score_templates", "category_id"):
            print("  ✓ category_id 列已存在，跳过添加")
        else:
            print("  + 添加列: score_templates.category_id (INTEGER, NULL)")
            conn.execute(text("""
                ALTER TABLE score_templates
                ADD COLUMN category_id INTEGER
            """))
            conn.commit()

        # 2. 添加外键约束（ON DELETE CASCADE）
        fk_name = "fk_score_templates_category"
        if constraint_exists(conn, "score_templates", fk_name):
            print(f"  ✓ 外键 {fk_name} 已存在，跳过添加")
        else:
            print(f"  + 添加外键: {fk_name} → template_category(id) ON DELETE CASCADE")
            conn.execute(text("""
                ALTER TABLE score_templates
                ADD CONSTRAINT fk_score_templates_category
                FOREIGN KEY (category_id) REFERENCES template_category(id)
                ON DELETE CASCADE
            """))
            conn.commit()

        # 3. 添加索引（template_category_id 上常用过滤：列出某分类下所有模板）
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_score_templates_category
            ON score_templates (category_id)
        """))
        conn.commit()

        # 4. 验证
        if not column_exists(conn, "score_templates", "category_id"):
            raise RuntimeError("迁移后 category_id 列仍不存在，请人工检查")
        if not constraint_exists(conn, "score_templates", "fk_score_templates_category"):
            raise RuntimeError("迁移后外键约束仍不存在，请人工检查")

    print("=" * 50)
    print("迁移完成！")
    print("=" * 50)
    print("\n后续步骤：")
    print("  1. 重启 idpython 服务")
    print("  2. 后台调用 POST /api/template-category 配置分类树（先建根，再建子）")
    print("  3. 给 score_templates 中需要迁移到新分类树的模板 UPDATE category_id = ?")
    print("  4. Layer 2 落地后，前端模板管理界面读 GET /api/template-category/leaf")
    return True


def rollback():
    print("回滚：移除 score_templates.category_id...")

    with sync_engine.connect() as conn:
        fk_name = "fk_score_templates_category"

        # 删除外键
        if constraint_exists(conn, "score_templates", fk_name):
            print(f"  - 删除外键: {fk_name}")
            conn.execute(text(f"""
                ALTER TABLE score_templates DROP CONSTRAINT {fk_name}
            """))
            conn.commit()

        # 删除索引
        conn.execute(text("DROP INDEX IF EXISTS idx_score_templates_category"))
        conn.commit()

        # 删除列
        if column_exists(conn, "score_templates", "category_id"):
            print("  - 删除列: score_templates.category_id")
            conn.execute(text("ALTER TABLE score_templates DROP COLUMN category_id"))
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