"""迁移脚本 (015)：permission 加 group 字段

═══════════════════════════════════════════════════════════════════════
目的
═══════════════════════════════════════════════════════════════════════
按 attribute 的同款设计，给 permission 表加：
  - group_code  VARCHAR(50)   NOT NULL   技术 key（前端 GROUP BY 用）
  - group_name  VARCHAR(100)  NOT NULL   显示名

不加 is_active / is_deprecated：
  permission 是代码层语义（接口要不要限制），
  对应入口是「不要这个接口就删 permission_code」，
  不存在软禁用的语义，因此 is_active / is_deprecated 都不加。

═══════════════════════════════════════════════════════════════════════
变更清单
═══════════════════════════════════════════════════════════════════════
Step 1: 加 group_code / group_name 字段（临时 nullable）
Step 2: 从 api_path 推断 group_code（按 "/" 二段前缀分桶），回填 group_name
Step 3: 改成 NOT NULL + 加 idx_permission_group 索引
Step 4: 同步迁移 rbac_service / schemas / models（不在本文件处理，但本脚本会
        打印提示）

═══════════════════════════════════════════════════════════════════════
执行
═══════════════════════════════════════════════════════════════════════
执行：python migrations/015_permission_group.py
回滚：python migrations/015_permission_group.py --rollback

═══════════════════════════════════════════════════════════════════════
前提
═══════════════════════════════════════════════════════════════════════
- 014 已执行（permission 表已稳定）
- 系统中已有 seed_permissions.py 写过的 permission 数据
"""
import sys
sys.path.insert(0, '.')

from sqlalchemy import text

from src.infra.database import sync_engine


# ============================================================
# 元数据查询
# ============================================================

def column_exists(conn, table: str, column: str) -> bool:
    return conn.execute(text("""
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = :t AND column_name = :c LIMIT 1
    """), {"t": table, "c": column}).first() is not None


def index_exists(conn, name: str) -> bool:
    return conn.execute(text("""
        SELECT 1 FROM pg_indexes
        WHERE schemaname = 'public' AND indexname = :i LIMIT 1
    """), {"i": name}).first() is not None


# ============================================================
# group_code 推导规则（与 seed_permissions.py / attribute 完全对齐）
# ============================================================

# ============================================================
# group_code 推导规则（与 seed_permissions.py 段位一一对齐）
# ============================================================
#
# 设计原则：由 sort_order 段位推导（不是 api_path），因为：
#   - api_path 是路由层，permission 是权限层；二者改变相互不影响
#   - permission_code 是模块语义；改名不应当影响分组
#   - 一旦分桶规则定下来，回填 + 前端绑定都不会再有歧义
#
# 段位映射（与 seed_permissions.py PERMISSIONS 段位一致）：
#
#   段位        group_code       中文名        实际 api_path 示例
#   200-299   user_admin       用户管理      /api/user/admin/...
#   300-399   role             角色管理      /api/system/role/...
#   400-499   permission       权限管理      /api/system/permission/...
#   500-599   template         模板管理      /api/bonus-template/...,
#                                            /api/template-category/...
#   700-799   rule             规则管理      /api/rule/...,
#                                            /api/rule-attribute/...
#   900-999   system           系统配置      /api/system/config/...
#   1000-1099 application     申请审核      /api/application/audit/...
#   1100-1199 proof           证明材料      /api/proof/...
#
# 说明：
#   /api/template-category/* 归在 template 段（500）——category 属于模板域
#   /api/rule-attribute/* 归在 rule 段（700）——attribute 属于规则域
#   任何不在以上段位的 sort_order（=0 / 150 / 9999...）→ "other" 兜底
#
SORT_ORDER_GROUP_BUCKETS = [
    (200,   299, "user_admin",   "用户管理"),
    (300,   399, "role",         "角色管理"),
    (400,   499, "permission",   "权限管理"),
    (500,   599, "template",     "模板管理"),
    (700,   799, "rule",         "规则管理"),
    (900,   999, "system",       "系统配置"),
    (1000, 1099, "application",  "申请审核"),
    (1100, 1199, "proof",        "证明材料"),
]


def derive_group_code(api_path: str | None, permission_code: str | None, sort_order: int | None) -> str:
    """按 sort_order 段位推导 group_code（与 seed_permissions.py 段位对齐）。

    参数 api_path / permission_code 在本规则下不被使用，保留参数签名是为了
    与 src.app.schemas.permission.derive_group_code 调用方兼容（如未来需要
    退回"按 code 前缀"作为 fallback，会用到这两个参数）。
    """
    if sort_order is not None:
        for lo, hi, gc, _gn in SORT_ORDER_GROUP_BUCKETS:
            if lo <= sort_order <= hi:
                return gc
    return "other"


def derive_group_name(group_code: str) -> str:
    """group_code → 显示名（中文）。"""
    for lo, hi, gc, gn in SORT_ORDER_GROUP_BUCKETS:
        if gc == group_code:
            return gn
    return "其他"


# ============================================================
# 正向迁移
# ============================================================

def migrate():
    print("开始迁移：permission 加 group 字段（015）...")
    print()

    with sync_engine.begin() as conn:
        # ---------- Step 1: 加字段（临时 nullable） ----------
        print("[Step 1] 加 group_code / group_name 字段（临时 nullable）")
        if not column_exists(conn, "permission", "group_code"):
            conn.execute(text(
                "ALTER TABLE public.permission "
                "ADD COLUMN group_code VARCHAR(50)"
            ))
            print("    + ADD COLUMN permission.group_code VARCHAR(50)")
        else:
            print("    ✓ permission.group_code 已存在")

        if not column_exists(conn, "permission", "group_name"):
            conn.execute(text(
                "ALTER TABLE public.permission "
                "ADD COLUMN group_name VARCHAR(100)"
            ))
            print("    + ADD COLUMN permission.group_name VARCHAR(100)")
        else:
            print("    ✓ permission.group_name 已存在")

        # ---------- Step 2: 回填 group_code / group_name ----------
        print()
        print("[Step 2] 回填 group_code / group_name")

        rows = conn.execute(text("""
            SELECT id, permission_code, api_path, sort_order, group_code, group_name
            FROM public.permission
            ORDER BY sort_order, id
        """)).all()

        if not rows:
            print("    ! permission 表为空，无需回填")
        else:
            update_count = 0
            skipped = 0
            for row in rows:
                pid, code, api_path, sort_order, cur_gc, cur_gn = row
                # 已回填过则跳过（幂等）
                if cur_gc and cur_gn:
                    skipped += 1
                    continue
                new_gc = derive_group_code(api_path, code, sort_order)
                new_gn = derive_group_name(new_gc)
                conn.execute(text("""
                    UPDATE public.permission
                    SET group_code = :gc, group_name = :gn
                    WHERE id = :id
                """), {"gc": new_gc, "gn": new_gn, "id": pid})
                update_count += 1

            print(f"    更新 {update_count} 条，跳过已填充 {skipped} 条")

        # ---------- Step 3: NOT NULL + 索引 ----------
        print()
        print("[Step 3] 改 NOT NULL + 加索引 idx_permission_group")

        conn.execute(text(
            "ALTER TABLE public.permission "
            "ALTER COLUMN group_code SET NOT NULL"
        ))
        conn.execute(text(
            "ALTER TABLE public.permission "
            "ALTER COLUMN group_name SET NOT NULL"
        ))
        print("    + ALTER COLUMN ... SET NOT NULL")

        if not index_exists(conn, "idx_permission_group"):
            conn.execute(text(
                "CREATE INDEX idx_permission_group "
                "ON public.permission (group_code)"
            ))
            print("    + CREATE INDEX idx_permission_group")
        else:
            print("    ✓ idx_permission_group 已存在")

    print()
    print("=" * 60)
    print("迁移 015 完成！")
    print("=" * 60)
    print()
    print("下一步：")
    print("  1. 同步 Python 模型 / Schema / VO（见 [Step 4] 说明）")
    print("  2. 重启 idpython 服务（让 ORM 加载新字段映射）")
    print("  3. 前端按 groupCode 做分组渲染（不强制，列表也可平铺）")
    return True


# ============================================================
# 回滚
# ============================================================

def rollback():
    print("回滚 015：移除 permission.group_code / group_name ...")

    with sync_engine.begin() as conn:
        if index_exists(conn, "idx_permission_group"):
            conn.execute(text("DROP INDEX IF EXISTS public.idx_permission_group"))
            print("  - DROP INDEX idx_permission_group")

        for col in ("group_name", "group_code"):
            if column_exists(conn, "permission", col):
                conn.execute(text(
                    f"ALTER TABLE public.permission DROP COLUMN IF EXISTS {col}"
                ))
                print(f"  - DROP COLUMN permission.{col}")

    print()
    print("回滚 015 完成")
    return True


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    if "--rollback" in sys.argv:
        rollback()
    else:
        migrate()
