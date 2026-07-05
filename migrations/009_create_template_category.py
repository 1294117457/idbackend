"""迁移脚本 (009)：创建 template_category 表（Layer 1 分类树）

背景：
- Layer 1 落地的核心表，统一管理分类层级、各级分值上限、is_leaf 状态机
- 与 ORM src.models.template_category.TemplateCategory 完全对齐

字段对齐表（与 ORM 模型一致）：
    id          SERIAL PRIMARY KEY                -- autoincrement
    name        VARCHAR(100) NOT NULL
    parent_id   INTEGER  REFERENCES template_category(id) ON DELETE CASCADE
    max_score   DECIMAL(5,2) NOT NULL             -- CHECK max_score >= 0
    is_leaf     BOOLEAN NOT NULL DEFAULT TRUE
    sort_order  INTEGER NOT NULL DEFAULT 0
    is_active   BOOLEAN NOT NULL DEFAULT TRUE
    description VARCHAR(255)
    created_at  TIMESTAMP                          -- Python 端写入，无 DB 默认
    updated_at  TIMESTAMP                          -- Python 端写入，无 DB 默认

索引：
    idx_template_category_parent_sort (parent_id, sort_order, id)
    idx_template_category_active      (is_active)

CHECK：
    ck_template_category_max_score_nonneg  max_score >= 0

执行：python migrations/009_create_template_category.py
回滚：python migrations/009_create_template_category.py --rollback
"""
import sys
sys.path.insert(0, '.')

from sqlalchemy import text
from src.infra.database import sync_engine


# ============================================================
# 元数据查询
# ============================================================
def table_exists(conn, table_name: str) -> bool:
    row = conn.execute(text("""
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = :t
        LIMIT 1
    """), {"t": table_name}).first()
    return row is not None


def index_exists(conn, index_name: str) -> bool:
    row = conn.execute(text("""
        SELECT 1
        FROM pg_indexes
        WHERE schemaname = 'public'
          AND indexname = :i
        LIMIT 1
    """), {"i": index_name}).first()
    return row is not None


def constraint_exists(conn, constraint_name: str) -> bool:
    row = conn.execute(text("""
        SELECT 1
        FROM information_schema.table_constraints
        WHERE table_schema = 'public'
          AND constraint_name = :c
        LIMIT 1
    """), {"c": constraint_name}).first()
    return row is not None


# ============================================================
# 正向迁移
# ============================================================
def migrate():
    print("开始迁移：创建 template_category 表（Layer 1）...")

    with sync_engine.begin() as conn:
        # ---------- 1. 建表 ----------
        if table_exists(conn, "template_category"):
            print("  ✓ template_category 表已存在，跳过建表")
        else:
            print("  + 创建表: template_category")
            conn.execute(text("""
                CREATE TABLE template_category (
                    id          SERIAL PRIMARY KEY,
                    name        VARCHAR(100) NOT NULL,
                    parent_id   INTEGER,
                    max_score   DECIMAL(5, 2) NOT NULL,
                    is_leaf     BOOLEAN NOT NULL DEFAULT TRUE,
                    sort_order  INTEGER NOT NULL DEFAULT 0,
                    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
                    description VARCHAR(255),
                    created_at  TIMESTAMP,
                    updated_at  TIMESTAMP,
                    CONSTRAINT fk_template_category_parent
                        FOREIGN KEY (parent_id)
                        REFERENCES template_category(id)
                        ON DELETE CASCADE
                )
            """))
            print("  + 创建表: template_category 完成")

        # ---------- 2. CHECK 约束 ----------
        check_name = "ck_template_category_max_score_nonneg"
        if constraint_exists(conn, check_name):
            print(f"  ✓ CHECK {check_name} 已存在，跳过")
        else:
            print(f"  + 添加 CHECK: {check_name}")
            conn.execute(text("""
                ALTER TABLE template_category
                ADD CONSTRAINT ck_template_category_max_score_nonneg
                CHECK (max_score >= 0)
            """))

        # ---------- 3. 索引 ----------
        for idx_name, idx_sql in [
            (
                "idx_template_category_parent_sort",
                "CREATE INDEX idx_template_category_parent_sort "
                "ON template_category (parent_id, sort_order, id)"
            ),
            (
                "idx_template_category_active",
                "CREATE INDEX idx_template_category_active "
                "ON template_category (is_active)"
            ),
        ]:
            if index_exists(conn, idx_name):
                print(f"  ✓ 索引 {idx_name} 已存在，跳过")
            else:
                print(f"  + 创建索引: {idx_name}")
                conn.execute(text(idx_sql))

        # ---------- 4. 验证 ----------
        if not table_exists(conn, "template_category"):
            raise RuntimeError("迁移后 template_category 表仍不存在，请人工检查")
        if not constraint_exists(conn, check_name):
            raise RuntimeError(f"迁移后 {check_name} 约束仍不存在，请人工检查")
        if not index_exists(conn, "idx_template_category_parent_sort"):
            raise RuntimeError("迁移后 parent_sort 索引仍不存在，请人工检查")
        if not index_exists(conn, "idx_template_category_active"):
            raise RuntimeError("迁移后 active 索引仍不存在，请人工检查")

    print("=" * 50)
    print("迁移完成！")
    print("=" * 50)
    print("\n表结构验证：")
    _describe_table()
    print("\n后续步骤：")
    print("  1. 执行迁移 010：python migrations/010_add_template_category_id_to_score_templates.py")
    print("  2. 跑权限种子：python -m scripts.seed_permissions")
    print("  3. 重启 idpython 服务")
    print("  4. 用 POST /api/template-category 建根节点 → 子节点")
    return True


def _describe_table():
    """打印表结构（来自 information_schema）"""
    with sync_engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'template_category'
            ORDER BY ordinal_position
        """)).all()
        print("    {:<15} {:<12} {:<10} {:<10}".format("column", "type", "nullable", "default"))
        for r in rows:
            print("    {:<15} {:<12} {:<10} {:<10}".format(
                r.column_name, r.data_type, r.is_nullable, str(r.column_default or "")
            ))


# ============================================================
# 回滚
# ============================================================
def rollback():
    """回滚迁移：删除 template_category 表"""
    print("回滚：删除 template_category 表...")

    with sync_engine.begin() as conn:
        # 因为 score_templates.category_id 有 ON DELETE CASCADE 指向此表
        # 回滚时若 010 已先执行，会一并级联删除 score_templates.category_id
        # 因此建议顺序：先回滚 010，再回滚 009
        if table_exists(conn, "template_category"):
            print("  - 删除表: template_category")
            conn.execute(text("DROP TABLE IF EXISTS template_category CASCADE"))
        else:
            print("  ✓ template_category 表不存在，无需删除")

    print("=" * 50)
    print("回滚完成！")
    print("=" * 50)
    print("\n注意：")
    print("  - 如果 010 已经执行，score_templates.category_id 列和外键也会被级联删除")
    print("  - 建议回滚顺序：先 --rollback 010，再 --rollback 009")
    return True


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--rollback', action='store_true', help='回滚迁移')
    args = parser.parse_args()

    if args.rollback:
        rollback()
    else:
        migrate()