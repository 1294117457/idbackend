"""迁移脚本 (012)：v4 设计落库

本迁移：
1. 清理旧表（demand_templates、rule_attributes、score_template_rules、rule_attribute_mapping、field_config、field_subcategory）
   - 注：demand_applications / evaluation_applications 不动（需求类业务后续单独迭代）
   - 注：score_applications / application_proofs 不动（申请层不在本迁移范围）
2. 创建 v4 新 5 张表：
   - template（聚合根）
   - rule（计分单位，含 type 字段）
   - attribute（选项 / 公式，含 type 字段）
   - template_rule（多对多关联）
   - rule_attribute（多对多关联）

执行：python migrations/012_v4_template_rule_attribute.py
回滚：python migrations/012_v4_template_rule_attribute.py --rollback

重要前提：
- score_templates 表改为 template（**重命名而不是新建**，数据迁移麻烦且不重要）
- field_id / subcategory_id / score_type / template_type / input_unit / created_by 等字段被废弃（v4 不需要）
- rule.attribute_code / attribute_value / input_interval 也废弃
- 旧数据保留在迁移前的备份表（如需）

═══════════════════════════════════════════════════════════════════════
后续清理（迁移 013）
═══════════════════════════════════════════════════════════════════════
执行 013 后，demand_applications + 所有 _bak 备份表会被 DROP，本脚本的 --rollback
将无法真正恢复旧数据（仅做幂等跳过）。如需保留回滚能力，请勿执行 013。
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
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = :t LIMIT 1
    """), {"t": table_name}).first()
    return row is not None


def column_exists(conn, table: str, column: str) -> bool:
    row = conn.execute(text("""
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = :t AND column_name = :c LIMIT 1
    """), {"t": table, "c": column}).first()
    return row is not None


def constraint_exists(conn, table: str, name: str) -> bool:
    row = conn.execute(text("""
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_schema = 'public' AND table_name = :t AND constraint_name = :c LIMIT 1
    """), {"t": table, "c": name}).first()
    return row is not None


def index_exists(conn, name: str) -> bool:
    row = conn.execute(text("""
        SELECT 1 FROM pg_indexes
        WHERE schemaname = 'public' AND indexname = :i LIMIT 1
    """), {"i": name}).first()
    return row is not None


# ============================================================
# 正向迁移
# ============================================================
def migrate():
    print("开始迁移：v4 设计落库（template / rule / attribute 5 张表）...")

    with sync_engine.begin() as conn:
        # ---------- Step 1: 备份 + 删除旧表 ----------
        # 备份旧 rule_attributes（v4 改为 attribute）
        if table_exists(conn, "rule_attributes") and not table_exists(conn, "rule_attributes_bak"):
            print("  + 备份旧表: rule_attributes → rule_attributes_bak")
            conn.execute(text("CREATE TABLE rule_attributes_bak AS TABLE rule_attributes"))
            conn.execute(text("DROP TABLE rule_attributes CASCADE"))

        # 备份旧 score_template_rules（v4 改为 rule）
        if table_exists(conn, "score_template_rules") and not table_exists(conn, "score_template_rules_bak"):
            print("  + 备份旧表: score_template_rules → score_template_rules_bak")
            conn.execute(text("CREATE TABLE score_template_rules_bak AS TABLE score_template_rules"))
            conn.execute(text("DROP TABLE score_template_rules CASCADE"))

        # 备份旧 rule_attribute_mapping（v4 改为 rule_attribute）
        if table_exists(conn, "rule_attribute_mapping") and not table_exists(conn, "rule_attribute_mapping_bak"):
            print("  + 备份旧表: rule_attribute_mapping → rule_attribute_mapping_bak")
            conn.execute(text("CREATE TABLE rule_attribute_mapping_bak AS TABLE rule_attribute_mapping"))
            conn.execute(text("DROP TABLE rule_attribute_mapping CASCADE"))

        # 备份旧 score_templates（v4 改为 template）
        if table_exists(conn, "score_templates") and not table_exists(conn, "score_templates_bak"):
            print("  + 备份旧表: score_templates → score_templates_bak")
            conn.execute(text("CREATE TABLE score_templates_bak AS TABLE score_templates"))
            conn.execute(text("DROP TABLE score_templates CASCADE"))

        # 备份旧 demand_templates（v4 删除，需求类走 user.extra_info）
        if table_exists(conn, "demand_templates") and not table_exists(conn, "demand_templates_bak"):
            print("  + 备份旧表: demand_templates → demand_templates_bak")
            conn.execute(text("CREATE TABLE demand_templates_bak AS TABLE demand_templates"))
            conn.execute(text("DROP TABLE demand_templates"))

        # 备份旧 field_config / field_subcategory（v4 删除，分类统一走 template_category）
        if table_exists(conn, "field_config") and not table_exists(conn, "field_config_bak"):
            print("  + 备份旧表: field_config → field_config_bak")
            conn.execute(text("CREATE TABLE field_config_bak AS TABLE field_config"))
            conn.execute(text("DROP TABLE field_config CASCADE"))

        if table_exists(conn, "field_subcategory") and not table_exists(conn, "field_subcategory_bak"):
            print("  + 备份旧表: field_subcategory → field_subcategory_bak")
            conn.execute(text("CREATE TABLE field_subcategory_bak AS TABLE field_subcategory"))
            conn.execute(text("DROP TABLE field_subcategory"))

        # ---------- Step 2: 创建 v4 新 5 张表 ----------

        # 2.1 template
        if not table_exists(conn, "template"):
            print("  + 创建表: template")
            conn.execute(text("""
                CREATE TABLE template (
                    id          SERIAL PRIMARY KEY,
                    name        VARCHAR(100) NOT NULL,
                    category_id INTEGER NOT NULL REFERENCES template_category(id) ON DELETE CASCADE,
                    max_score   DECIMAL(5, 2) NOT NULL,
                    review_count INTEGER NOT NULL DEFAULT 1,
                    sort_order  INTEGER NOT NULL DEFAULT 0,
                    description TEXT,
                    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at  TIMESTAMP,
                    updated_at  TIMESTAMP,
                    CONSTRAINT ck_template_max_score_nonneg CHECK (max_score >= 0)
                )
            """))
            print("    + 索引 idx_template_category")
            conn.execute(text("CREATE INDEX idx_template_category ON template (category_id)"))
            print("    + 索引 idx_template_active")
            conn.execute(text("CREATE INDEX idx_template_active ON template (is_active)"))
        else:
            print("  ✓ template 表已存在")

        # 2.2 rule
        if not table_exists(conn, "rule"):
            print("  + 创建表: rule")
            conn.execute(text("""
                CREATE TABLE rule (
                    id          SERIAL PRIMARY KEY,
                    type        VARCHAR(20) NOT NULL DEFAULT 'CONDITION',
                    score       DECIMAL(5, 2),
                    name        VARCHAR(100) NOT NULL,
                    sort_order  INTEGER NOT NULL DEFAULT 0,
                    description TEXT,
                    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at  TIMESTAMP,
                    updated_at  TIMESTAMP,
                    CONSTRAINT ck_rule_type_enum CHECK (type IN ('CONDITION', 'TRANSFORM'))
                )
            """))
            print("    + 索引 idx_rule_type")
            conn.execute(text("CREATE INDEX idx_rule_type ON rule (type)"))
            print("    + 索引 idx_rule_active")
            conn.execute(text("CREATE INDEX idx_rule_active ON rule (is_active)"))
        else:
            print("  ✓ rule 表已存在")

        # 2.3 attribute
        if not table_exists(conn, "attribute"):
            print("  + 创建表: attribute")
            conn.execute(text("""
                CREATE TABLE attribute (
                    id          SERIAL PRIMARY KEY,
                    name        VARCHAR(100) NOT NULL,
                    group_code  VARCHAR(50) NOT NULL,
                    group_name  VARCHAR(100) NOT NULL,
                    type        VARCHAR(20) NOT NULL DEFAULT 'CONDITION',
                    value       TEXT NOT NULL DEFAULT '',
                    input_min   DECIMAL(10, 4),
                    input_max   DECIMAL(10, 4),
                    sort_order  INTEGER NOT NULL DEFAULT 0,
                    description TEXT,
                    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at  TIMESTAMP,
                    updated_at  TIMESTAMP,
                    CONSTRAINT ck_attribute_type_enum CHECK (type IN ('CONDITION', 'TRANSFORM'))
                )
            """))
            print("    + 索引 idx_attribute_group")
            conn.execute(text("CREATE INDEX idx_attribute_group ON attribute (group_code)"))
            print("    + 索引 idx_attribute_active")
            conn.execute(text("CREATE INDEX idx_attribute_active ON attribute (is_active)"))
        else:
            print("  ✓ attribute 表已存在")

        # 2.4 template_rule
        if not table_exists(conn, "template_rule"):
            print("  + 创建表: template_rule")
            conn.execute(text("""
                CREATE TABLE template_rule (
                    id          SERIAL PRIMARY KEY,
                    template_id INTEGER NOT NULL REFERENCES template(id) ON DELETE CASCADE,
                    rule_id     INTEGER NOT NULL REFERENCES rule(id),
                    created_at  TIMESTAMP,
                    updated_at  TIMESTAMP,
                    CONSTRAINT uk_template_rule UNIQUE (template_id, rule_id)
                )
            """))
            print("    + 索引 idx_template_rule_template")
            conn.execute(text("CREATE INDEX idx_template_rule_template ON template_rule (template_id)"))
            print("    + 索引 idx_template_rule_rule")
            conn.execute(text("CREATE INDEX idx_template_rule_rule ON template_rule (rule_id)"))
        else:
            print("  ✓ template_rule 表已存在")

        # 2.5 rule_attribute
        if not table_exists(conn, "rule_attribute"):
            print("  + 创建表: rule_attribute")
            conn.execute(text("""
                CREATE TABLE rule_attribute (
                    id           SERIAL PRIMARY KEY,
                    rule_id      INTEGER NOT NULL REFERENCES rule(id) ON DELETE CASCADE,
                    attribute_id INTEGER NOT NULL REFERENCES attribute(id) ON DELETE CASCADE,
                    created_at   TIMESTAMP,
                    updated_at   TIMESTAMP,
                    CONSTRAINT uk_rule_attribute UNIQUE (rule_id, attribute_id)
                )
            """))
            print("    + 索引 idx_rule_attribute_rule")
            conn.execute(text("CREATE INDEX idx_rule_attribute_rule ON rule_attribute (rule_id)"))
            print("    + 索引 idx_rule_attribute_attribute")
            conn.execute(text("CREATE INDEX idx_rule_attribute_attribute ON rule_attribute (attribute_id)"))
        else:
            print("  ✓ rule_attribute 表已存在")

        # ---------- Step 3: 修复 application 的外键（score_templates → template，score_template_rules → rule） ----------
        if column_exists(conn, "score_applications", "template_id"):
            fk_name = "fk_application_template_v4"
            if not constraint_exists(conn, "score_applications", fk_name):
                print("  + 修复 application.template_id 外键 → template(id)")
                # 先删除旧外键（如果存在）
                old_fks = conn.execute(text("""
                    SELECT constraint_name FROM information_schema.table_constraints
                    WHERE table_schema = 'public' AND table_name = 'score_applications'
                    AND constraint_type = 'FOREIGN KEY'
                    AND constraint_name LIKE '%template%'
                """)).fetchall()
                for (old_fk,) in old_fks:
                    try:
                        conn.execute(text(f"ALTER TABLE score_applications DROP CONSTRAINT {old_fk}"))
                    except Exception:
                        pass  # 旧 FK 可能不兼容，强制跳过
                conn.execute(text("""
                    ALTER TABLE score_applications
                    ADD CONSTRAINT fk_application_template_v4
                    FOREIGN KEY (template_id) REFERENCES template(id)
                """))
            else:
                print("  ✓ score_applications.template_id 已指向 template")

        if column_exists(conn, "score_applications", "rule_id"):
            fk_name = "fk_application_rule_v4"
            if not constraint_exists(conn, "score_applications", fk_name):
                print("  + 修复 application.rule_id 外键 → rule(id)")
                old_fks = conn.execute(text("""
                    SELECT constraint_name FROM information_schema.table_constraints
                    WHERE table_schema = 'public' AND table_name = 'score_applications'
                    AND constraint_type = 'FOREIGN KEY'
                    AND constraint_name LIKE '%rule%'
                """)).fetchall()
                for (old_fk,) in old_fks:
                    try:
                        conn.execute(text(f"ALTER TABLE score_applications DROP CONSTRAINT {old_fk}"))
                    except Exception:
                        pass
                conn.execute(text("""
                    ALTER TABLE score_applications
                    ADD CONSTRAINT fk_application_rule_v4
                    FOREIGN KEY (rule_id) REFERENCES rule(id)
                """))
            else:
                print("  ✓ score_applications.rule_id 已指向 rule")

    print("=" * 50)
    print("迁移完成！")
    print("=" * 50)
    print("\n后续步骤：")
    print("  1. 重启 idpython 服务（让 ORM 重新加载新表映射）")
    print("  2. 重新跑权限种子：python -m scripts.seed_permissions")
    print("  3. 后台管理界面用 POST /api/template 创建模板")
    print("  4. 用 POST /api/rule 创建规则，POST /api/rule-attribute 创建属性")
    print("\n【警告】旧数据已备份到 _bak 后缀的表：")
    print("  - rule_attributes_bak / score_template_rules_bak / rule_attribute_mapping_bak")
    print("  - score_templates_bak / demand_templates_bak / field_config_bak / field_subcategory_bak")
    print("  - 如确认 v4 稳定运行后，可手动 DROP 这些备份表")
    return True


# ============================================================
# 回滚
# ============================================================
def rollback():
    """回滚迁移：从 _bak 备份恢复旧表（如果存在），删除 v4 新表"""
    print("回滚：v4 设计回滚到旧版...")

    with sync_engine.begin() as conn:
        # 先删除 v4 新表
        for table in ["rule_attribute", "template_rule", "attribute", "rule", "template"]:
            if table_exists(conn, table):
                print(f"  - 删除 v4 表: {table}")
                conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))

        # 恢复旧表（从备份）
        restore_pairs = [
            ("rule_attributes_bak", "rule_attributes"),
            ("score_template_rules_bak", "score_template_rules"),
            ("rule_attribute_mapping_bak", "rule_attribute_mapping"),
            ("score_templates_bak", "score_templates"),
            ("demand_templates_bak", "demand_templates"),
            ("field_config_bak", "field_config"),
            ("field_subcategory_bak", "field_subcategory"),
        ]
        for bak, target in restore_pairs:
            if table_exists(conn, bak) and not table_exists(conn, target):
                print(f"  - 恢复旧表: {bak} → {target}")
                conn.execute(text(f"ALTER TABLE {bak} RENAME TO {target}"))

        # 回滚 application 的外键（恢复指向旧表）
        if column_exists(conn, "score_applications", "template_id"):
            fk_name = "fk_application_template_v4"
            if constraint_exists(conn, "score_applications", fk_name):
                print("  - 移除 application.template_id 新外键")
                conn.execute(text(f"ALTER TABLE score_applications DROP CONSTRAINT {fk_name}"))

    print("=" * 50)
    print("回滚完成！")
    print("=" * 50)
    print("\n【注意】回滚后需要重启服务让 ORM 恢复旧表映射。")
    return True


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--rollback', action='store_true')
    args = parser.parse_args()

    if args.rollback:
        rollback()
    else:
        migrate()