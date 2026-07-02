"""RBAC 初始化数据脚本 v2

运行此脚本初始化 RBAC 默认数据：
    python -m src.scripts.init_rbac_data

说明：
- 角色：super_admin / admin / reviewer / user
- 权限表采用最终字段：permission_code / permission_name / api_path / description / sort_order / status
- 角色与权限采用幂等写入，重复执行不会重复插入
"""
import asyncio
import os
import sys

from sqlalchemy import select

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.infra.database import AsyncSessionLocal
from src.models.user import Permission, Role, RolePermission


ROLES_DATA = [
    {
        "role_code": "super_admin",
        "role_name": "超级管理员",
        "description": "可管理账户、修改系统配置、全部业务功能",
        "sort_order": 1,
        "is_system": True,
    },
    {
        "role_code": "admin",
        "role_name": "管理员",
        "description": "模板管理、学生管理、审核管理，不能操作账户",
        "sort_order": 2,
        "is_system": True,
    },
    {
        "role_code": "reviewer",
        "role_name": "审核员",
        "description": "审核学生保研加分申请",
        "sort_order": 3,
        "is_system": True,
    },
    {
        "role_code": "user",
        "role_name": "学生",
        "description": "普通学生用户，可提交保研加分申请",
        "sort_order": 4,
        "is_system": True,
    },
]

PERMISSIONS_DATA = [
    {"permission_code": "admin:login", "permission_name": "管理端登录", "api_path": None, "description": "管理端登录权限", "sort_order": 0},
    {"permission_code": "account", "permission_name": "账户管理", "api_path": None, "description": "账户管理菜单", "sort_order": 5},
    {"permission_code": "account:view", "permission_name": "账户列表", "api_path": "/api/system/account/list", "description": "查看账户列表", "sort_order": 1},
    {"permission_code": "account:create", "permission_name": "创建账户", "api_path": "/api/system/account/create", "description": "创建账户", "sort_order": 2},
    {"permission_code": "account:edit", "permission_name": "编辑账户", "api_path": "/api/system/account/update", "description": "编辑账户", "sort_order": 3},
    {"permission_code": "account:delete", "permission_name": "删除账户", "api_path": "/api/system/account/delete", "description": "删除账户", "sort_order": 4},
    {"permission_code": "account:assign_role", "permission_name": "分配角色", "api_path": "/api/system/account/assign-role", "description": "为账户分配角色", "sort_order": 5},
    {"permission_code": "account:role_manage", "permission_name": "角色管理", "api_path": "/api/system/role/list", "description": "角色管理菜单", "sort_order": 2},
    {"permission_code": "account:permission_manage", "permission_name": "权限管理", "api_path": "/api/system/permission/list", "description": "权限管理菜单", "sort_order": 3},
    {"permission_code": "system_config", "permission_name": "系统配置", "api_path": None, "description": "系统配置菜单", "sort_order": 99},
    {"permission_code": "system_config:view", "permission_name": "查看配置", "api_path": "/api/system/config", "description": "查看系统配置", "sort_order": 1},
    {"permission_code": "system_config:agent", "permission_name": "Agent配置", "api_path": "/api/system/config/agent", "description": "Agent 配置", "sort_order": 2},
    {"permission_code": "system_config:smtp", "permission_name": "邮件配置", "api_path": "/api/system/config/smtp", "description": "邮件配置", "sort_order": 3},
    {"permission_code": "system_config:edit", "permission_name": "编辑配置", "api_path": "/api/system/config/update", "description": "编辑系统配置", "sort_order": 4},
    {"permission_code": "template", "permission_name": "模板管理", "api_path": None, "description": "模板管理菜单", "sort_order": 3},
    {"permission_code": "template:view", "permission_name": "查看模板", "api_path": "/api/template/list", "description": "查看模板列表", "sort_order": 1},
    {"permission_code": "template:create", "permission_name": "创建模板", "api_path": "/api/template/create", "description": "创建模板", "sort_order": 2},
    {"permission_code": "template:edit", "permission_name": "编辑模板", "api_path": "/api/template/update", "description": "编辑模板", "sort_order": 3},
    {"permission_code": "template:delete", "permission_name": "删除模板", "api_path": "/api/template/delete", "description": "删除模板", "sort_order": 4},
    {"permission_code": "student", "permission_name": "学生管理", "api_path": None, "description": "学生管理菜单", "sort_order": 2},
    {"permission_code": "student:view", "permission_name": "查看学生", "api_path": "/api/student/list", "description": "查看学生列表", "sort_order": 1},
    {"permission_code": "student:edit", "permission_name": "编辑学生", "api_path": "/api/student/update", "description": "编辑学生", "sort_order": 2},
    {"permission_code": "review", "permission_name": "审核管理", "api_path": None, "description": "审核管理菜单", "sort_order": 4},
    {"permission_code": "review:pending", "permission_name": "待审核", "api_path": "/api/review/pending", "description": "查看待审核列表", "sort_order": 1},
    {"permission_code": "review:approved", "permission_name": "已通过", "api_path": "/api/review/approved", "description": "查看已通过列表", "sort_order": 2},
    {"permission_code": "review:approve", "permission_name": "通过审核", "api_path": "/api/review/{id}/approve", "description": "通过审核", "sort_order": 10},
    {"permission_code": "review:reject", "permission_name": "拒绝审核", "api_path": "/api/review/{id}/reject", "description": "拒绝审核", "sort_order": 11},
    {"permission_code": "apply", "permission_name": "加分申请", "api_path": None, "description": "加分申请菜单", "sort_order": 1},
    {"permission_code": "apply:create", "permission_name": "提交申请", "api_path": "/api/apply/create", "description": "提交申请", "sort_order": 1},
    {"permission_code": "apply:my", "permission_name": "我的申请", "api_path": "/api/apply/my", "description": "查看我的申请", "sort_order": 2},
    {"permission_code": "apply:view", "permission_name": "查看申请详情", "api_path": "/api/apply/{id}", "description": "查看申请详情", "sort_order": 3},
]

ROLE_PERMISSIONS = {
    "super_admin": [
        "admin:login",
        "account:view", "account:create", "account:edit", "account:delete", "account:assign_role",
        "account:role_manage", "account:permission_manage",
        "system_config:view", "system_config:agent", "system_config:smtp", "system_config:edit",
        "template:view", "template:create", "template:edit", "template:delete",
        "student:view", "student:edit",
        "review:pending", "review:approved", "review:approve", "review:reject",
        "apply:create", "apply:my", "apply:view",
    ],
    "admin": [
        "admin:login",
        "template:view", "template:create", "template:edit", "template:delete",
        "student:view", "student:edit",
        "review:pending", "review:approved", "review:approve", "review:reject",
        "apply:create", "apply:my", "apply:view",
    ],
    "reviewer": [
        "student:view",
        "review:pending", "review:approved", "review:approve", "review:reject",
        "apply:view",
    ],
    "user": [
        "apply:create", "apply:my", "apply:view",
    ],
}


async def init_rbac_data():
    async with AsyncSessionLocal() as db:
        try:
            created_roles = {}
            for role_data in ROLES_DATA:
                result = await db.execute(select(Role).where(Role.role_code == role_data["role_code"]))
                existing_role = result.scalar_one_or_none()
                if existing_role:
                    created_roles[role_data["role_code"]] = existing_role
                    print(f"[跳过] 角色已存在: {role_data['role_code']}")
                else:
                    role = Role(**role_data, status=True)
                    db.add(role)
                    await db.flush()
                    created_roles[role_data["role_code"]] = role
                    print(f"[创建] 角色: {role_data['role_code']}")

            created_permissions = {}
            for perm_data in PERMISSIONS_DATA:
                result = await db.execute(
                    select(Permission).where(Permission.permission_code == perm_data["permission_code"])
                )
                existing_perm = result.scalar_one_or_none()
                if existing_perm:
                    created_permissions[perm_data["permission_code"]] = existing_perm
                    print(f"[跳过] 权限已存在: {perm_data['permission_code']}")
                else:
                    permission = Permission(
                        permission_code=perm_data["permission_code"],
                        permission_name=perm_data["permission_name"],
                        api_path=perm_data["api_path"],
                        description=perm_data.get("description"),
                        sort_order=perm_data.get("sort_order", 0),
                        status=True,
                    )
                    db.add(permission)
                    await db.flush()
                    created_permissions[perm_data["permission_code"]] = permission
                    print(f"[创建] 权限: {perm_data['permission_code']}")

            await db.flush()

            for role_code, perm_codes in ROLE_PERMISSIONS.items():
                role = created_roles.get(role_code)
                if not role:
                    continue
                for perm_code in perm_codes:
                    perm = created_permissions.get(perm_code)
                    if not perm:
                        continue
                    result = await db.execute(
                        select(RolePermission)
                        .where(RolePermission.role_id == role.id)
                        .where(RolePermission.permission_id == perm.id)
                    )
                    if not result.scalar_one_or_none():
                        db.add(RolePermission(role_id=role.id, permission_id=perm.id))
                        print(f"[分配] {role_code} -> {perm_code}")

            await db.commit()

            print("\n" + "=" * 50)
            print("[完成] RBAC 初始化数据已写入")
            print("=" * 50)
            print("角色: super_admin / admin / reviewer / user")
            print(f"权限数量: {len(created_permissions)}")
            print("=" * 50)

        except Exception as e:
            await db.rollback()
            print(f"[错误] 初始化失败: {e}")
            import traceback
            traceback.print_exc()
            raise


if __name__ == "__main__":
    print("=" * 50)
    print("RBAC 数据初始化")
    print("=" * 50)
    asyncio.run(init_rbac_data())
