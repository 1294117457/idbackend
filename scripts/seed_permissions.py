"""权限种子数据脚本

按 api_path → permission_code 写入 permission 表，并给 admin / reviewer / super_admin
等角色绑对应权限。

执行：
    cd /home/dustp/codes/idproject/idpython
    python -m scripts.seed_permissions

幂等：permission_code 已存在则跳过；角色权限绑定已存在则跳过。
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infra.database import AsyncSessionLocal
from src.models.user import Permission, Role, RolePermission


# path → (permission_code, permission_name, sort_order)
PERMISSIONS = [
    # ============== 用户管理（需 admin） ==============
    ("/api/user/admin/list", "user:admin:list", "用户管理-列表", 201),
    ("/api/user/admin/create", "user:admin:create", "用户管理-创建", 202),
    ("/api/user/admin/batch-create", "user:admin:batch_create", "用户管理-批量创建", 203),
    ("/api/user/admin/{user_id}", "user:admin:delete", "用户管理-删除", 204),
    ("/api/user/admin/{user_id}/status", "user:admin:update_status", "用户管理-改状态", 205),
    ("/api/user/{user_id}/roles", "user:role:list", "用户-查看角色", 206),
    ("/api/user/{user_id}/roles/assign", "user:role:assign", "用户-分配角色", 207),

    # ============== 角色管理（需 admin） ==============
    ("/api/system/role/list", "role:list", "角色-列表", 301),
    ("/api/system/role/{role_id}", "role:detail", "角色-详情", 302),
    ("/api/system/role/{role_id}", "role:delete", "角色-删除", 303),
    ("/api/system/role/create", "role:create", "角色-创建", 304),
    ("/api/system/role/update", "role:update", "角色-更新", 305),
    ("/api/system/role/{role_id}/permissions", "role:perm:list", "角色权限-列表", 306),
    ("/api/system/role/assignPermissions", "role:perm:assign", "角色权限-分配", 307),

    # ============== 权限管理（需 admin） ==============
    ("/api/system/permission/list", "permission:list", "权限-列表", 401),
    ("/api/system/permission/interfaces", "permission:interfaces", "权限-接口扫描", 402),
    ("/api/system/permission/scan-interfaces", "permission:scan", "权限-执行扫描", 403),
    ("/api/system/permission/create", "permission:create", "权限-创建", 404),
    ("/api/system/permission/update", "permission:update", "权限-更新", 405),
    ("/api/system/permission/{permission_id}", "permission:delete", "权限-删除", 406),

    # ============== 模板（bonus-template，需 admin） ==============
    ("/api/bonus-template/list", "template:list", "模板-列表", 501),
    ("/api/bonus-template/by-category", "template:list", "模板-按分类", 502),
    ("/api/bonus-template/{template_id}", "template:detail", "模板-详情", 503),
    ("/api/bonus-template", "template:create", "模板-创建", 504),
    ("/api/bonus-template/{template_id}", "template:update", "模板-更新", 505),
    ("/api/bonus-template/{template_id}", "template:delete", "模板-删除", 506),
    ("/api/bonus-template/{template_id}/rules", "template:bind_rule", "模板-绑规则", 507),
    ("/api/bonus-template/{template_id}/rules/{rule_id}", "template:unbind_rule", "模板-解绑规则", 508),

    # ============== 模板分类树（template-category，Layer 1，需 admin） ==============
    # 注：FastAPI 路由匹配按注册顺序。模板分类前缀 /api/template-category 比模板 /api/bonus-template 短，
    # 为避免前缀误匹配，把精确路径放在前面（seed_permissions 也按 path→code 维护，无顺序依赖，但代码顺序保持清晰）
    ("/api/template-category/tree", "template_category:read", "模板分类-树", 510),
    ("/api/template-category/list", "template_category:read", "模板分类-列表", 511),
    ("/api/template-category/leaf", "template_category:read", "模板分类-叶子列表", 512),
    ("/api/template-category", "template_category:create", "模板分类-创建", 513),
    ("/api/template-category/{category_id}", "template_category:read", "模板分类-详情", 514),
    ("/api/template-category/{category_id}", "template_category:update", "模板分类-更新", 515),
    ("/api/template-category/{category_id}", "template_category:delete", "模板分类-删除", 516),
    ("/api/template-category/{category_id}/delete-preview", "template_category:read", "模板分类-删除预览", 517),

    # ============== Rule（rule，需 admin） ==============
    ("/api/rule/list", "rule:list", "规则-列表", 701),
    ("/api/rule/{rule_id}", "rule:detail", "规则-详情", 702),
    ("/api/rule", "rule:create", "规则-创建", 703),
    ("/api/rule/{rule_id}", "rule:update", "规则-更新", 704),
    ("/api/rule/{rule_id}", "rule:delete", "规则-删除", 705),
    ("/api/rule/{rule_id}/attributes", "rule:bind_attribute", "规则-绑属性", 706),
    ("/api/rule/{rule_id}/attributes/{attribute_id}", "rule:unbind_attribute", "规则-解绑属性", 707),

    # ============== Attribute（rule-attribute，需 admin） ==============
    ("/api/rule-attribute/list", "attribute:list", "属性-列表", 711),
    ("/api/rule-attribute/{attribute_id}", "attribute:detail", "属性-详情", 712),
    ("/api/rule-attribute", "attribute:create", "属性-创建", 713),
    ("/api/rule-attribute/{attribute_id}", "attribute:update", "属性-更新", 714),
    ("/api/rule-attribute/{attribute_id}", "attribute:delete", "属性-删除", 715),

    # ============== 系统配置（需白名单用户，admin_login 资格） ==============
    ("/api/system/config", "system:config:view", "系统配置-查看", 901),
    ("/api/system/config/agent", "system:config:agent:view", "Agent 配置-查看", 902),
    ("/api/system/config/agent", "system:config:agent:edit", "Agent 配置-编辑", 903),
    ("/api/system/config/smtp", "system:config:smtp:view", "SMTP 配置-查看", 904),
    ("/api/system/config/smtp", "system:config:smtp:edit", "SMTP 配置-编辑", 905),

    # ============== 申请审核（reviewer） ==============
    ("/api/application/pending", "application:pending:list", "申请-待审核列表", 1001),
    ("/api/application/audit/pending", "application:audit:pending", "申请-审核待办", 1002),
    ("/api/application/audit/history", "application:audit:history", "申请-审核历史", 1003),
    ("/api/application/audit/approve", "application:audit:approve", "申请-审核通过", 1004),
    ("/api/application/audit/reject", "application:audit:reject", "申请-审核驳回", 1005),
    ("/api/application/audit/revoke", "application:audit:revoke", "申请-审核撤销", 1006),

    # ============== 证明材料审核（reviewer） ==============
    ("/api/proof/{proof_id}/approve", "proof:approve", "证明-审核通过", 1101),
    ("/api/proof/{proof_id}/reject", "proof:reject", "证明-审核驳回", 1102),
    ("/api/proof/{proof_id}/override", "proof:override", "证明-覆盖重判", 1103),
]


# 角色 → 应绑定的权限码集合
ROLE_PERMISSIONS = {
    "admin": [
        # admin 拿到所有管理类权限（不含系统配置）
        "user:admin:list", "user:admin:create", "user:admin:batch_create",
        "user:admin:delete", "user:admin:update_status",
        "user:role:list", "user:role:assign",
        "role:list", "role:detail", "role:delete", "role:create", "role:update",
        "role:perm:list", "role:perm:assign",
        "permission:list", "permission:interfaces", "permission:scan",
        "permission:create", "permission:update", "permission:delete",
        # Template / Rule / Attribute（v4）
        "template:list", "template:detail", "template:create", "template:update", "template:delete",
        "template:bind_rule", "template:unbind_rule",
        "template_category:read", "template_category:create", "template_category:update", "template_category:delete",
        "rule:list", "rule:detail", "rule:create", "rule:update", "rule:delete",
        "rule:bind_attribute", "rule:unbind_attribute",
        "attribute:list", "attribute:detail", "attribute:create", "attribute:update", "attribute:delete",
        "application:pending:list", "application:audit:pending", "application:audit:history",
        "application:audit:approve", "application:audit:reject", "application:audit:revoke",
        "proof:approve", "proof:reject", "proof:override",
    ],
    "reviewer": [
        "application:pending:list", "application:audit:pending", "application:audit:history",
        "application:audit:approve", "application:audit:reject", "application:audit:revoke",
        "proof:approve", "proof:reject", "proof:override",
    ],
    "super_admin": ["*"],  # 标记为全权限（在 PermissionMiddleware 中白名单用户直接通过）
}


async def seed_permissions(db: AsyncSession) -> int:
    """写入权限行，返回新增数"""
    inserted = 0
    for path, code, name, sort_order in PERMISSIONS:
        existing = await db.execute(
            select(Permission).where(Permission.permission_code == code)
        )
        perm = existing.scalar_one_or_none()
        if perm:
            # 更新 api_path / name（防止新增 path）
            if perm.api_path != path or perm.permission_name != name or perm.sort_order != sort_order:
                perm.api_path = path
                perm.permission_name = name
                perm.sort_order = sort_order
            continue
        db.add(Permission(
            permission_code=code,
            permission_name=name,
            api_path=path,
            sort_order=sort_order,
            status=True,
        ))
        inserted += 1
    return inserted


async def seed_role_permissions(db: AsyncSession) -> int:
    """为角色分配权限，返回新增绑定数"""
    inserted = 0
    for role_code, perm_codes in ROLE_PERMISSIONS.items():
        if "*" in perm_codes:
            # super_admin 不需要 RolePermission 行，中间件走白名单
            continue
        result = await db.execute(
            select(Role).where(Role.role_code == role_code)
        )
        role = result.scalar_one_or_none()
        if not role:
            print(f"  ! 角色 {role_code} 不存在，跳过")
            continue

        # 收集 code → Permission.id
        result = await db.execute(
            select(Permission).where(Permission.permission_code.in_(perm_codes))
        )
        perms = result.scalars().all()
        if len(perms) != len(perm_codes):
            found = {p.permission_code for p in perms}
            missing = set(perm_codes) - found
            print(f"  ! 角色 {role_code} 的权限码缺失: {missing}")

        for perm in perms:
            existing = await db.execute(
                select(RolePermission).where(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == perm.id,
                )
            )
            if existing.scalar_one_or_none():
                continue
            db.add(RolePermission(role_id=role.id, permission_id=perm.id))
            inserted += 1
    return inserted


async def main():
    async with AsyncSessionLocal() as db:
        try:
            print("写入 permission 行...")
            p_count = await seed_permissions(db)
            print(f"  新增 {p_count} 条")

            print("写入 RolePermission 绑定...")
            r_count = await seed_role_permissions(db)
            print(f"  新增 {r_count} 条")

            await db.commit()
            print("提交完成")
        except Exception as e:
            await db.rollback()
            print(f"失败回滚: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(main())
