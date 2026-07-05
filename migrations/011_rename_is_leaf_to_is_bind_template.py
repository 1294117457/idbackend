"""迁移脚本 (011)：template_category.is_leaf → is_bind_template

背景（业务语义调整）：
- 旧设计：is_leaf 表示"无子节点的状态机字段"，由 service.create_child/delete 维护
- 新设计：分类层级是 N-ary 树（一个父可以多个子），不再用 is_leaf 描述"是否有子"
- 新约束：一个分类节点上**可以绑多个 Template**（不再是一对一）
- is_bind_template 的含义翻转：
    TRUE  = 该节点**已绑定** template（叶子已"被占用"，不能再加子，也不能再绑 template
            —— 实际上允许绑多个，要不要去重由业务决定，第一版不强制去重）
    FALSE = 该节点未绑 template，可以加子，也可以绑 template
- 本迁移将列重命名；同时按新语义把所有现有行统一重置为 FALSE
  （历史数据 = 无 template 绑定，统一符合 FALSE）

字段对齐表（与新 ORM 完全对齐）：
    id              SERIAL PRIMARY KEY
    name            VARCHAR(100) NOT NULL
    parent_id       INTEGER REFERENCES template_category(id) ON DELETE CASCADE
    max_score       DECIMAL(5,2) NOT NULL CHECK (max_score >= 0)
    is_bind_template BOOLEAN NOT NULL DEFAULT FALSE      ← 由 is_leaf 重命名
    sort_order      INTEGER NOT NULL DEFAULT 0
    is_active       BOOLEAN NOT NULL DEFAULT TRUE
    description     VARCHAR(255)
    created_at      TIMESTAMP
    updated_at      TIMESTAMP

业务约束（service 层实现，非 DB 层）：
- create_child：父节点必须 is_bind_template=FALSE（新语义：父未绑 template 才可加子）
                与子节点数量无关（N-ary 树）
- create_template_bind：被绑分类必须 is_bind_template=FALSE（或允许 TRUE = 追加，
                第一版允许追加，第二版可加 check）
- 当 template 被解除绑定 → service 端异步回滚 is_bind_template（本期暂不实现）

执行：python migrations/011_rename_is_leaf_to_is_bind_template.py
回滚：python migrations/011_rename_is_leaf_to_is_bind_template.py --rollback
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
    print("开始迁移：template_category.is_leaf → is_bind_template...")

    with sync_engine.begin() as conn:
        # ---------- 1. 重命名列 ----------
        if not column_exists(conn, "template_category", "is_leaf"):
            print("  ✓ is_leaf 列已不存在，跳过重命名")
        else:
            print("  + 重命名列: is_leaf → is_bind_template")
            conn.execute(text("""
                ALTER TABLE template_category
                RENAME COLUMN is_leaf TO is_bind_template
            """))
            print("    ✓ 列名已改")

        # ---------- 2. 修改默认值：从 TRUE 改为 FALSE ----------
        # 新业务语义下，新节点的"默认绑定状态"应该明确：
        # 默认未绑 = FALSE（避免误判"是不是叶子"被混淆为"是否绑了 template"）
        # 这里直接重置 DEFAULT；同时把历史行也统一为 FALSE（按现状历史数据无 template）
        print("  + 调整默认值 + 重置历史数据为 FALSE")
        conn.execute(text("""
            ALTER TABLE template_category
            ALTER COLUMN is_bind_template SET DEFAULT FALSE
        """))
        conn.execute(text("""
            UPDATE template_category
            SET is_bind_template = FALSE
        """))

        # ---------- 3. 验证 ----------
        if column_exists(conn, "template_category", "is_leaf"):
            raise RuntimeError("迁移后 is_leaf 列仍存在，请人工检查")
        if not column_exists(conn, "template_category", "is_bind_template"):
            raise RuntimeError("迁移后 is_bind_template 列仍不存在，请人工检查")

        # 打印最终现状
        rows = conn.execute(text("""
            SELECT id, name, parent_id, is_bind_template, is_active
            FROM template_category
            ORDER BY id
        """)).all()
        print("\n迁移后 template_category 现状：")
        print("    {:<5} {:<20} {:<12} {:<18} {:<8}".format(
            "id", "name", "parent_id", "is_bind_template", "is_active"
        ))
        for r in rows:
            print("    {:<5} {:<20} {:<12} {:<18} {:<8}".format(
                r.id, r.name, str(r.parent_id if r.parent_id is not None else "NULL"),
                str(r.is_bind_template), str(r.is_active)
            ))

    print("=" * 50)
    print("迁移完成！")
    print("=" * 50)
    print("\n后续步骤：")
    print("  1. 重启 idpython 服务（让 ORM 重新加载新字段映射）")
    print("  2. 重新跑前端页面验证：现在一个分类可以加 N 个子分类")
    print("  3. 第一版已绑 template 后不再允许加子（service 校验 is_bind_template）")
    print("  4. 解除绑定 → 改回 is_bind_template=FALSE 的 service 在后续 PR 补")
    return True


def rollback():
    """回滚迁移：is_bind_template → is_leaf（恢复旧语义）"""
    print("回滚：is_bind_template → is_leaf...")

    with sync_engine.begin() as conn:
        if column_exists(conn, "template_category", "is_bind_template"):
            print("  - 重命名回: is_bind_template → is_leaf")
            conn.execute(text("""
                ALTER TABLE template_category
                RENAME COLUMN is_bind_template TO is_leaf
            """))
            # 恢复默认值
            conn.execute(text("""
                ALTER TABLE template_category
                ALTER COLUMN is_leaf SET DEFAULT TRUE
            """))
        else:
            print("  ✓ is_bind_template 列已不存在，跳过回滚")

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