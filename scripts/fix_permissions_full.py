"""RBAC 权限数据全量重置脚本

【作用】
解决历史问题：
  1. 老 init_rbac_data.py 写的 path 是 /api/template/*（无连字符）
  2. 新代码跑的 path 是 /api/demand-template/*、/api/bonus-template/*、/api/rule-attribute/* 等
  3. 两套前缀混在 DB 里，导致 permission_middleware 查不到 code → 默认放行 → 权限形同虚设

【策略】
1. 以本脚本中声明的 PERMISSIONS 列表为最终真源 (path, code, name, sort)
   - 对每个 (code, path)：UPDATE 已有记录的 api_path / name / sort；缺失则 INSERT
2. 重置 admin / reviewer / super_admin 三个角色的权限绑定：
   - 先按 role_id DELETE RolePermission 中所有当前绑定
   - 再按本脚本中 ROLE_PERMISSIONS 重新 INSERT
3. 整段在单个事务里，失败回滚，绝不留半套脏数据

【执行】
    cd /home/dustp/codes/idproject/idpython
    python -m scripts.fix_permissions_full

【已实现路由对照表（必须保持与本文件一致）】
  /api/demand-template/list             POST   demand_template.py:44
  /api/demand-template/create          POST   demand_template.py:62
  /api/demand-template/{template_id}   PUT    demand_template.py
  /api/demand-template/{template_id}   DELETE demand_template.py
  /api/bonus-template/list             POST   bonus_template.py (按 seed)
  /api/bonus-template/{template_id}    GET    bonus_template.py
  /api/bonus-template/create           POST   bonus_template.py
  /api/bonus-template/{template_id}    PUT    bonus_template.py
  /api/bonus-template/{template_id}    DELETE bonus_template.py
  /api/rule-attribute/*                *      attribute.py
  /api/field-config/subcategory/*       *      field_config routes
  /api/application/audit/*             *      application.py
  /api/proof/{proof_id}/*              *      proof routes
  /api/demand-application/all          GET    application demand routes
  /api/system/role/*                   *      user.py / role routes
  /api/system/permission/*             *      permission routes
  /api/system/config                   *      system_config.py
"""
import asyncio
import os
import sys

from sqlalchemy import delete, select

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.infra.database import AsyncSessionLocal
from src.models.user import Permission, Role, RolePermission


# =========== 权限真源：path → (code, name, sort) ===========
PERMISSIONS: list[tuple[str, str, str, int]] = [
    # ---- 用户管理（admin） ----
    ("/api/user/admin/list", "user:admin:list", "用户管理-列表", 201),
    ("/api/user/admin/create", "user:admin:create", "用户管理-创建", 202),
    ("/api/user/admin/batch-create", "user:admin:batch_create", "用户管理-批量创建", 203),
    ("/api/user/admin/{user_id}", "user:admin:delete", "用户管理-删除", 204),
    ("/api/user/admin/{user_id}/status", "user:admin:update_status", "用户管理-改状态", 205),
    ("/api/user/{user_id}/roles", "user:role:list", "用户-查看角色", 206),
    ("/api/user/{user_id}/roles/assign", "user:role:assign", "用户-分配角色", 207),

    # ---- 角色管理（admin） ----
    ("/api/system/role/list", "role:list", "角色-列表", 301),
    ("/api/system/role/create", "role:create", "角色-创建", 304),
    ("/api/system/role/update", "role:update", "角色-更新", 305),
    ("/api/system/role/{role_id}", "role:detail", "角色-详情", 302),
    ("/api/system/role/{role_id}/permissions", "role:perm:list", "角色权限-列表", 306),
    ("/api/system/role/assignPermissions", "role:perm:assign", "角色权限-分配", 307),

    # ---- 权限管理（admin） ----
    ("/api/system/permission/list", "permission:list", "权限-列表", 401),
    ("/api/system/permission/interfaces", "permission:interfaces", "权限-接口扫描", 402),
    ("/api/system/permission/scan-interfaces", "permission:scan", "权限-执行扫描", 403),
    ("/api/system/permission/create", "permission:create", "权限-创建", 404),
    ("/api/system/permission/update", "permission:update", "权限-更新", 405),
    ("/api/system/permission/{permission_id}", "permission:delete", "权限-删除", 406),

    # ---- bonus-template（admin） ----
    ("/api/bonus-template/list", "template:list", "模板-列表", 501),
    ("/api/bonus-template/{template_id}", "template:detail", "模板-详情", 502),
    ("/api/bonus-template/create", "template:create", "模板-创建", 503),
    ("/api/bonus-template/{template_id}", "template:update", "模板-更新", 504),
    ("/api/bonus-template/{template_id}", "template:delete", "模板-删除", 505),

    # ---- demand-template（admin） ----
    ("/api/demand-template/list", "demand_template:list", "需求模板-列表", 601),
    ("/api/demand-template/create", "demand_template:create", "需求模板-创建", 602),
    ("/api/demand-template/{template_id}", "demand_template:update", "需求模板-更新", 603),
    ("/api/demand-template/{template_id}", "demand_template:delete", "需求模板-删除", 604),

    # ---- 字段配置（admin） ----
    ("/api/field-config/list/all", "field_config:list_all", "字段配置-全量", 801),
    ("/api/field-config/subcategory/list", "field_config:subcategory:list", "字段配置-子分类列表", 802),
    ("/api/field-config/subcategory", "field_config:subcategory:create", "字段配置-子分类创建", 803),
    ("/api/field-config/subcategory/{subcategory_id}", "field_config:subcategory:update", "字段配置-子分类更新", 804),
    ("/api/field-config/subcategory/{subcategory_id}", "field_config:subcategory:delete", "字段配置-子分类删除", 805),

    # ---- 系统配置（admin） ----
    ("/api/system/config", "system:config:view", "系统配置-查看", 901),
    ("/api/system/config/agent", "system:config:agent:view", "Agent 配置-查看", 902),
    ("/api/system/config/agent", "system:config:agent:edit", "Agent 配置-编辑", 903),
    ("/api/system/config/smtp", "system:config:smtp:view", "SMTP 配置-查看", 904),
    ("/api/system/config/smtp", "system:config:smtp:edit", "SMTP 配置-编辑", 905),

    # ---- 申请审核（reviewer / admin） ----
    ("/api/application/pending", "application:pending:list", "申请-待审核列表", 1001),
    ("/api/application/audit/pending", "application:audit:pending", "申请-审核待办", 1002),
    ("/api/application/audit/history", "application:audit:history", "申请-审核历史", 1003),
    ("/api/application/audit/approve", "application:audit:approve", "申请-审核通过", 1004),
    ("/api/application/audit/reject", "application:audit:reject", "申请-审核驳回", 1005),
    ("/api/application/audit/revoke", "application:audit:revoke", "申请-审核撤销", 1006),

    # ---- 证明材料审核 ----
    ("/api/proof/{proof_id}/approve", "proof:approve", "证明-审核通过", 1101),
    ("/api/proof/{proof_id}/reject", "proof:reject", "证明-审核驳回", 1102),
    ("/api/proof/{proof_id}/override", "proof:override", "证明-覆盖重判", 1103),

    # ---- 需求申请审核 ----
    ("/api/demand-application/all", "demand_application:list_all", "需求申请-全部列表", 1201),
]


# =========== 角色 → 应绑定的 permission_code ===========
ROLE_PERMISSIONS: dict[str, list[str]] = {
    "super_admin": [c for _, c, _, _ in PERMISSIONS],  # 超管拿所有

    "admin": [
        "user:admin:list", "user:admin:create", "user:admin:batch_create",
        "user:admin:delete", "user:admin:update_status",
        "user:role:list", "user:role:assign",
        "role:list", "role:detail", "role:create", "role:update",
        "role:perm:list", "role:perm:assign",
        "permission:list", "permission:interfaces", "permission:scan",
        "permission:create", "permission:update", "permission:delete",
        "template:list", "template:detail", "template:create", "template:update", "template:delete",
        "demand_template:list", "demand_template:create", "demand_template:update", "demand_template:delete",
        "field_config:list_all", "field_config:subcategory:list",
        "field_config:subcategory:create", "field_config:subcategory:update", "field_config:subcategory:delete",
        "application:pending:list", "application:audit:pending", "application:audit:history",
        "application:audit:approve", "application:audit:reject", "application:audit:revoke",
        "proof:approve", "proof:reject", "proof:override",
        "demand_application:list_all",
    ],

    "reviewer": [
        "application:pending:list", "application:audit:pending", "application:audit:history",
        "application:audit:approve", "application:audit:reject",
        "proof:approve", "proof:reject", "proof:override",
    ],
}


# 兼容老 path → 新 path 的映射（DELETE 而非 UPDATE，避免 schema 飘移）
DEPRECATED_PERMISSION_CODES: list[str] = [
    # 老 init_rbac_data.py 写的、且与新 path 冲突的 code
    "template",            # 老的菜单类
    "template:view",       # /api/template/list   → 已废弃
    "template:create",     # /api/template/create  → 已废弃
    "template:edit",       # /api/template/update  → 已废弃
    "template:delete",     # /api/template/delete  → 已废弃
    "account", "account:view", "account:create", "account:edit", "account:delete",
    "account:assign_role", "account:role_manage", "account:permission_manage",
    "student", "student:view", "student:edit",
    "review", "review:pending", "review:approved", "review:approve", "review:reject",
    "apply", "apply:create", "apply:my", "apply:view",
    "system_config", "system_config:view", "system_config:agent", "system_config:smtp", "system_config:edit",
    "admin:login",  # 系统资源菜单角色
]


async def main():
    async with AsyncSessionLocal() as db:
        try:
            # ---------- 1. 拉取全部现有 permission ----------
            result = await db.execute(select(Permission))
            existing = {p.permission_code: p for p in result.scalars().all()}
            print(f"[1] 当前 DB 中现有 permission 数量: {len(existing)}")

            # ---------- 2. 对每个 (code, path, name, sort)：UPSERT ----------
            print("[2] 开始对齐所有 permission ...")
            updated, inserted = 0, 0
            for path, code, name, sort in PERMISSIONS:
                perm = existing.get(code)
                if perm is None:
                    db.add(Permission(
                        permission_code=code,
                        permission_name=name,
                        api_path=path,
                        sort_order=sort,
                        status=True,
                    ))
                    inserted += 1
                else:
                    changed = False
                    if perm.api_path != path:
                        perm.api_path = path
                        changed = True
                    if perm.permission_name != name:
                        perm.permission_name = name
                        changed = True
                    if perm.sort_order != sort:
                        perm.sort_order = sort
                        changed = True
                    if changed:
                        updated += 1
            print(f"    新增 {inserted} 条；更新 {updated} 条")

            # ---------- 3. 删除过期的 permission 记录 ----------
            # 先把要删的 id 找出来（要同步清掉 RolePermission 外键引用）
            result = await db.execute(
                select(Permission.id).where(Permission.permission_code.in_(DEPRECATED_PERMISSION_CODES))
            )
            stale_ids = [r[0] for r in result.all()]
            if stale_ids:
                # 清理过期 role-permission 关联
                await db.execute(
                    delete(RolePermission).where(RolePermission.permission_id.in_(stale_ids))
                )
                # 删 permission 本体
                await db.execute(
                    delete(Permission).where(Permission.id.in_(stale_ids))
                )
                print(f"[3] 删除 {len(stale_ids)} 条过期 permission（并清关联 RolePermission）")
            else:
                print("[3] 没有需要清理的过期 permission")

            # ---------- 4. 重新建立 admin / reviewer / super_admin 角色绑定 ----------
            # 拿一下最新 permission 映射 code → id
            await db.flush()
            result = await db.execute(select(Permission.permission_code, Permission.id))
            code_to_id = {r[0]: r[1] for r in result.all()}

            target_roles = list(ROLE_PERMISSIONS.keys())
            result = await db.execute(select(Role).where(Role.role_code.in_(target_roles)))
            roles = {r.role_code: r for r in result.scalars().all()}

            print("[4] 重建角色权限绑定 ...")
            for role_code, perm_codes in ROLE_PERMISSIONS.items():
                role = roles.get(role_code)
                if role is None:
                    print(f"    [跳过] 角色不存在: {role_code}")
                    continue
                # 清掉该角色现有所有 RolePermission
                await db.execute(
                    delete(RolePermission).where(RolePermission.role_id == role.id)
                )
                # 重新 INSERT
                bound = 0
                for perm_code in perm_codes:
                    pid = code_to_id.get(perm_code)
                    if pid is None:
                        print(f"    [缺失] {role_code} -> {perm_code} （该 code 不在 PERMISSIONS 中）")
                        continue
                    db.add(RolePermission(role_id=role.id, permission_id=pid))
                    bound += 1
                print(f"    {role_code:12s}  新绑定 {bound:3d} 条")

            await db.commit()
            print("\n" + "=" * 60)
            print("[OK] permission 表 + 角色绑定 已全量重置")
            print("=" * 60)

        except Exception as e:
            await db.rollback()
            print(f"[FAIL] 出错回滚: {e}")
            import traceback
            traceback.print_exc()
            raise


if __name__ == "__main__":
    print("=" * 60)
    print("RBAC 权限全量重置脚本")
    print("=" * 60)
    asyncio.run(main())