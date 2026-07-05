"""迁移脚本 (013)：删除 v3 旧表 + _bak 备份表

数据库当前为空、开发期，直接 DROP 干净即可。

═══════════════════════════════════════════════════════════════════════
删除清单（按"业务废弃"顺序，业务独立表先 DROP，备份表后 DROP）
═══════════════════════════════════════════════════════════════════════
1. demand_applications        — 旧需求申请表（v4 已废弃，无 _bak）
2. demand_templates_bak       — 012 备份
3. field_config_bak           — 012 备份
4. field_subcategory_bak      — 012 备份
5. rule_attribute_mapping_bak — 012 备份
6. rule_attributes_bak        — 012 备份
7. score_template_rules_bak   — 012 备份
8. score_templates_bak        — 012 备份

═══════════════════════════════════════════════════════════════════════
保留的 v4 新表（已符合简洁命名要求）
═══════════════════════════════════════════════════════════════════════
- template
- rule
- attribute
- template_rule
- rule_attribute
- template_category

执行：python migrations/013_drop_legacy_tables.py
回滚：无（开发期直接 DROP，不做恢复）
"""
import sys
sys.path.insert(0, '.')

from sqlalchemy import text
from src.infra.database import sync_engine


LEGACY_TABLES = [
    # 业务层独立旧表
    "demand_applications",

    # 012 迁移留下的 _bak 备份表
    "demand_templates_bak",
    "field_config_bak",
    "field_subcategory_bak",
    "rule_attribute_mapping_bak",
    "rule_attributes_bak",
    "score_template_rules_bak",
    "score_templates_bak",
]


def table_exists(conn, table_name: str) -> bool:
    return conn.execute(text("""
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = :t LIMIT 1
    """), {"t": table_name}).first() is not None


def migrate():
    print(f"开始迁移：DROP {len(LEGACY_TABLES)} 张无用表...")
    print()

    with sync_engine.begin() as conn:
        deleted_count = 0
        for table_name in LEGACY_TABLES:
            if not table_exists(conn, table_name):
                print(f"  ✓ {table_name} 不存在，跳过")
                continue
            print(f"  - DROP TABLE {table_name} CASCADE")
            conn.execute(text(f"DROP TABLE {table_name} CASCADE"))
            deleted_count += 1

    print()
    print("=" * 50)
    print(f"迁移完成：成功 DROP {deleted_count} 张表")
    print("=" * 50)
    return True


if __name__ == "__main__":
    migrate()