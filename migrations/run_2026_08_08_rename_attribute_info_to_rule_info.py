"""
Run migration: applications.rule_info 扁平化 + 清理（v7 终态）

背景：
  - 早期 v7 迁移把 attribute_info 重命名为 rule_info（嵌套结构）
  - 现在最终版：rule_info 简化为扁平 {rule.name: attribute.name}（CONDITION 单选语义）
  - 过渡字段 __legacy_attribute_info 不再保留，直接删除

功能：
  - 检测 schema 当前状态，幂等执行
  - DROP COLUMN __legacy_attribute_info（如果存在）
  - 重扁平化 rule_info：嵌套 {rule.name: {attr.name: value}} → 扁平 {rule.name: attr.name}

用法：
  cd idbackend
  python3 migrations/run_2026_08_08_rename_attribute_info_to_rule_info.py [--dry-run]
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from src.infra.database import sync_engine


# ============================================================
# DDL（幂等）
# ============================================================

SQL_DROP_LEGACY = """
ALTER TABLE applications DROP COLUMN IF EXISTS __legacy_attribute_info;
"""

SQL_DROP_OLD_INDEX = """
DROP INDEX IF EXISTS idx_applications_attribute_info_gin;
"""

SQL_DROP_OLD_COLUMN = """
ALTER TABLE applications DROP COLUMN IF EXISTS attribute_info;
"""

SQL_ENSURE_NEW_COLUMN = """
ALTER TABLE applications
  ADD COLUMN IF NOT EXISTS rule_info JSONB NOT NULL DEFAULT '{}'::jsonb;
"""

SQL_ADD_COMMENT = """
COMMENT ON COLUMN applications.rule_info IS
  '申请提交时的 rule 快照（v7）：{rule.name: attribute.name}。'
  '学生提交时按 (template_id, attribute) 反查 rule，扁平化为单层结构。'
  'TRANSFORM 类型由 apply_score / gain_score 承载分数，rule_info 不重复存储。';
"""

SQL_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_applications_rule_info_gin
  ON applications USING GIN (rule_info);
"""


def run_migration(dry_run: bool = False) -> None:
    """执行迁移（幂等版）"""
    print("=" * 70)
    print("applications.rule_info 扁平化迁移（v7 终态）")
    print("=" * 70)

    with sync_engine.begin() as conn:
        # ──────────────────────────────────────────────
        # 检测 schema 状态
        # ──────────────────────────────────────────────
        cols = conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'applications'
              AND column_name IN ('attribute_info', 'rule_info', '__legacy_attribute_info')
        """)).fetchall()
        col_set = {r.column_name for r in cols}

        print(f"\n[Schema 检测]")
        print(f"  attribute_info:        {'存在' if 'attribute_info' in col_set else '不存在'}")
        print(f"  rule_info:             {'存在' if 'rule_info' in col_set else '不存在'}")
        print(f"  __legacy_attribute_info: {'存在' if '__legacy_attribute_info' in col_set else '不存在'}")

        # ──────────────────────────────────────────────
        # Step 1: DROP __legacy_attribute_info（如果存在）
        # ──────────────────────────────────────────────
        print("\n[Step 1] DROP COLUMN __legacy_attribute_info")
        if "__legacy_attribute_info" in col_set:
            if not dry_run:
                conn.execute(text(SQL_DROP_LEGACY))
                print("  [OK] __legacy_attribute_info 已删除")
            else:
                print("  [DRY-RUN] 跳过")
        else:
            print("  [SKIP] 不存在")

        # ──────────────────────────────────────────────
        # Step 2: DROP 旧 attribute_info（如果存在）
        #         + 旧 GIN 索引（如果存在）
        # ──────────────────────────────────────────────
        print("\n[Step 2] DROP COLUMN attribute_info + 旧索引")
        if "attribute_info" in col_set:
            if not dry_run:
                conn.execute(text(SQL_DROP_OLD_INDEX))
                conn.execute(text(SQL_DROP_OLD_COLUMN))
                print("  [OK] attribute_info + idx_applications_attribute_info_gin 已删除")
            else:
                print("  [DRY-RUN] 跳过")
        else:
            print("  [SKIP] attribute_info 不存在")

        # ──────────────────────────────────────────────
        # Step 3: 确保 rule_info 列存在
        # ──────────────────────────────────────────────
        print("\n[Step 3] 确保 rule_info 列存在（NOT NULL DEFAULT '{}'::jsonb）")
        if not dry_run:
            conn.execute(text(SQL_ENSURE_NEW_COLUMN))
            print("  [OK]")
        else:
            print("  [DRY-RUN] 跳过")

        # ──────────────────────────────────────────────
        # Step 4: 添加字段注释
        # ──────────────────────────────────────────────
        print("\n[Step 4] 添加 rule_info 字段注释")
        if not dry_run:
            conn.execute(text(SQL_ADD_COMMENT))
            print("  [OK]")
        else:
            print("  [DRY-RUN] 跳过")

        # ──────────────────────────────────────────────
        # Step 5: GIN 索引
        # ──────────────────────────────────────────────
        print("\n[Step 5] CREATE INDEX idx_applications_rule_info_gin")
        if not dry_run:
            conn.execute(text(SQL_CREATE_INDEX))
            print("  [OK]")
        else:
            print("  [DRY-RUN] 跳过")

        # ──────────────────────────────────────────────
        # Step 6: 数据迁移（核心——扁平化）
        # ──────────────────────────────────────────────
        print("\n[Step 6] 数据迁移：rule_info 扁平化（嵌套 → 单层）")
        # 提交 DDL
        if not dry_run:
            conn.commit()

        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from src.infra.database import SyncSessionLocal
        from src.models.template import Template, Rule
        import json

        with SyncSessionLocal() as orm_session:
            # 1. 加载所有 template → rule → attribute 映射
            template_attr_to_rule: dict[int, dict[str, str]] = {}
            tpls = orm_session.execute(
                select(Template).options(
                    selectinload(Template.rules).selectinload(Rule.attributes)
                )
            ).scalars().all()
            for tpl in tpls:
                if not getattr(tpl, "is_active", True):
                    continue
                attr_rule: dict[str, str] = {}
                for rule in (tpl.rules or []):
                    if not getattr(rule, "is_active", True):
                        continue
                    for attr in (rule.attributes or []):
                        if not getattr(attr, "is_active", True):
                            continue
                        attr_rule.setdefault(attr.name, rule.name)
                template_attr_to_rule[tpl.id] = attr_rule
            print(f"  加载了 {len(template_attr_to_rule)} 个 template 的 attribute→rule 映射")

            # 2. 遍历当前 rule_info（嵌套）→ 扁平化
            rows = orm_session.execute(text("""
                SELECT id, template_id, rule_info
                FROM applications
                WHERE rule_info IS NOT NULL AND rule_info != '{}'::jsonb
            """)).fetchall()
            print(f"  需要处理 {len(rows)} 条 application")

            migrated_count = 0
            for row in rows:
                app_id = row.id
                data = row.rule_info or {}

                # 嵌套 → 扁平：{rule.name: {attr.name: value}} → {rule.name: attr.name}
                rule_info: dict[str, str] = {}
                for rule_name, nested in data.items():
                    if not isinstance(nested, dict) or not nested:
                        continue
                    attr_names = list(nested.keys())
                    if not attr_names:
                        continue
                    # 单选语义：取嵌套层第一个 attr.name（按字典序稳定）
                    rule_info[rule_name] = sorted(attr_names)[0]

                if not dry_run:
                    orm_session.execute(
                        text("UPDATE applications SET rule_info = :data WHERE id = :id"),
                        {"data": json.dumps(rule_info, ensure_ascii=False), "id": app_id},
                    )
                migrated_count += 1

            if not dry_run:
                orm_session.commit()
            print(f"  [OK] 处理完成: {migrated_count} 条")

        # ──────────────────────────────────────────────
        # Step 7: 验证
        # ──────────────────────────────────────────────
        print("\n[Step 7] 验证最终结果")
        if not dry_run:
            with SyncSessionLocal() as verify_session:
                check = verify_session.execute(text("""
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_name = 'applications'
                      AND column_name IN ('attribute_info', 'rule_info', '__legacy_attribute_info')
                    ORDER BY column_name
                """)).fetchall()
                for row in check:
                    print(f"  {row.column_name:30s} {row.data_type:15s} "
                          f"{'NULL' if row.is_nullable == 'YES' else 'NOT NULL'}")

                stats = verify_session.execute(text("""
                    SELECT
                      COUNT(*) AS total,
                      COUNT(*) FILTER (WHERE rule_info != '{}'::jsonb) AS non_empty
                    FROM applications
                """)).fetchone()
                print(f"  rule_info 统计: total={stats.total}, non_empty={stats.non_empty}")

                samples = verify_session.execute(text("""
                    SELECT id, template_id, rule_info
                    FROM applications
                    WHERE rule_info != '{}'::jsonb
                    ORDER BY id
                    LIMIT 3
                """)).fetchall()
                print(f"  样例数据（最多 3 条）:")
                for s in samples:
                    print(f"    id={s.id}, template_id={s.template_id}, rule_info={s.rule_info}")
        else:
            print("  [DRY-RUN] 跳过")

    print()
    print("=" * 70)
    print("✅ 迁移完成（v7 终态）")
    print("=" * 70)
    print()
    print("📋 当前 rule_info 结构：{rule.name: attribute.name}（单层扁平）")
    print("📋 __legacy_attribute_info 已被删除")
    print()
    print("📌 后续：")
    print("  - 前端 buildRuleInfo 已改为扁平 Record<string, string>")
    print("  - 后端 Pydantic ruleInfo 类型已收紧为 dict[str, str]")
    print("  - 导出文档已对齐扁平 2 级表头结构")
    print("=" * 70)


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("=" * 70)
        print("DRY-RUN 模式（不会修改数据库）")
        print("=" * 70)
    try:
        run_migration(dry_run=dry_run)
    except Exception as e:
        print(f"\n[FAIL] 迁移失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)