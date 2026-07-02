"""RBAC 初始化数据脚本 v2

运行此脚本初始化 RBAC 默认数据：
    python -m src.scripts.init_rbac_data

权限设计（针对保研加分场景）：

角色层级：
- super_admin: 超级管理员，可管理账户、修改系统配置、全部业务功能
- admin: 普通管理员，模板管理、学生管理、审核管理，不能操作账户
- reviewer: 审核员，审核功能
- user: 学生，注册自动分配，提交申请

SYSTEM_ACCOUNTS (zch):
- 隐藏的顶层权限白名单
- 内部机制，不在 UI 暴露
- 自动获取全部权限
"""
import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.infra.database import AsyncSessionLocal
from src.models.user import Role, Permission, UserRole, RolePermission
from sqlalchemy import select


async def init_rbac_data():
    """初始化 RBAC 默认数据"""
    async with AsyncSessionLocal() as db:
        try:
            # ========== 1. 创建角色 ==========
            roles_data = [
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

            created_roles = {}
            for role_data in roles_data:
                result = await db.execute(
                    select(Role).where(Role.role_code == role_data["role_code"])
                )
                existing_role = result.scalar_one_or_none()

                if existing_role:
                    print(f"[跳过] 角色已存在: {role_data['role_code']}")
                    created_roles[role_data["role_code"]] = existing_role
                else:
                    role = Role(**role_data, status=True)
                    db.add(role)
                    await db.flush()
                    created_roles[role_data["role_code"]] = role
                    print(f"[创建] 角色: {role_data['role_code']}")

            await db.flush()

            # ========== 2. 创建权限 ==========
            permissions_data = [
                # ========== 管理端登录权限 ==========
                {
                    "permission_code": "admin:login",
                    "permission_name": "管理端登录",
                    "module": "system",
                    "parent_id": None,
                    "is_menu": False,
                    "sort_order": 0,
                },
                # ========== 账户管理 (super_admin only) ==========
                {
                    "permission_code": "account",
                    "permission_name": "账户管理",
                    "module": "account",
                    "parent_id": None,
                    "is_menu": True,
                    "icon": "User",
                    "route_path": "activity",
                    "sort_order": 5,
                },
                {
                    "permission_code": "account:view",
                    "permission_name": "账户列表",
                    "module": "account",
                    "parent_id": None,
                    "is_menu": True,
                    "route_path": "activity/index",
                    "component_path": "@/views/account-manage/index.vue",
                    "sort_order": 1,
                },
                {
                    "permission_code": "account:create",
                    "permission_name": "创建账户",
                    "module": "account",
                    "parent_id": None,
                    "is_menu": False,
                    "sort_order": 2,
                },
                {
                    "permission_code": "account:edit",
                    "permission_name": "编辑账户",
                    "module": "account",
                    "parent_id": None,
                    "is_menu": False,
                    "sort_order": 3,
                },
                {
                    "permission_code": "account:delete",
                    "permission_name": "删除账户",
                    "module": "account",
                    "parent_id": None,
                    "is_menu": False,
                    "sort_order": 4,
                },
                {
                    "permission_code": "account:assign_role",
                    "permission_name": "分配角色",
                    "module": "account",
                    "parent_id": None,
                    "is_menu": False,
                    "sort_order": 5,
                },
                {
                    "permission_code": "account:role_manage",
                    "permission_name": "角色管理",
                    "module": "account",
                    "parent_id": None,
                    "is_menu": True,
                    "route_path": "activity/role",
                    "component_path": "@/views/account-manage/role.vue",
                    "sort_order": 2,
                },
                {
                    "permission_code": "account:permission_manage",
                    "permission_name": "权限管理",
                    "module": "account",
                    "parent_id": None,
                    "is_menu": True,
                    "route_path": "activity/permission",
                    "component_path": "@/views/account-manage/permission.vue",
                    "sort_order": 3,
                },

                # ========== 系统配置 (super_admin only) ==========
                {
                    "permission_code": "system_config",
                    "permission_name": "系统配置",
                    "module": "system_config",
                    "parent_id": None,
                    "is_menu": True,
                    "icon": "Setting",
                    "route_path": "system-config",
                    "sort_order": 99,
                },
                {
                    "permission_code": "system_config:view",
                    "permission_name": "查看配置",
                    "module": "system_config",
                    "parent_id": None,
                    "is_menu": True,
                    "route_path": "system-config/index",
                    "component_path": "@/views/system-config/index.vue",
                    "sort_order": 1,
                },
                {
                    "permission_code": "system_config:agent",
                    "permission_name": "Agent配置",
                    "module": "system_config",
                    "parent_id": None,
                    "is_menu": False,
                    "sort_order": 2,
                },
                {
                    "permission_code": "system_config:smtp",
                    "permission_name": "邮件配置",
                    "module": "system_config",
                    "parent_id": None,
                    "is_menu": False,
                    "sort_order": 3,
                },
                {
                    "permission_code": "system_config:edit",
                    "permission_name": "编辑配置",
                    "module": "system_config",
                    "parent_id": None,
                    "is_menu": False,
                    "sort_order": 4,
                },

                # ========== 模板管理 (super_admin, admin) ==========
                {
                    "permission_code": "template",
                    "permission_name": "模板管理",
                    "module": "template",
                    "parent_id": None,
                    "is_menu": True,
                    "icon": "Document",
                    "route_path": "template",
                    "sort_order": 3,
                },
                {
                    "permission_code": "template:view",
                    "permission_name": "查看模板",
                    "module": "template",
                    "parent_id": None,
                    "is_menu": True,
                    "route_path": "template/index",
                    "component_path": "@/views/template/index.vue",
                    "sort_order": 1,
                },
                {
                    "permission_code": "template:create",
                    "permission_name": "创建模板",
                    "module": "template",
                    "parent_id": None,
                    "is_menu": False,
                    "sort_order": 2,
                },
                {
                    "permission_code": "template:edit",
                    "permission_name": "编辑模板",
                    "module": "template",
                    "parent_id": None,
                    "is_menu": False,
                    "sort_order": 3,
                },
                {
                    "permission_code": "template:delete",
                    "permission_name": "删除模板",
                    "module": "template",
                    "parent_id": None,
                    "is_menu": False,
                    "sort_order": 4,
                },

                # ========== 学生管理 (super_admin, admin, reviewer) ==========
                {
                    "permission_code": "student",
                    "permission_name": "学生管理",
                    "module": "student",
                    "parent_id": None,
                    "is_menu": True,
                    "icon": "School",
                    "route_path": "student",
                    "sort_order": 2,
                },
                {
                    "permission_code": "student:view",
                    "permission_name": "查看学生",
                    "module": "student",
                    "parent_id": None,
                    "is_menu": True,
                    "route_path": "student/index",
                    "component_path": "@/views/student/index.vue",
                    "sort_order": 1,
                },
                {
                    "permission_code": "student:edit",
                    "permission_name": "编辑学生",
                    "module": "student",
                    "parent_id": None,
                    "is_menu": False,
                    "sort_order": 2,
                },

                # ========== 审核管理 (super_admin, admin, reviewer) ==========
                {
                    "permission_code": "review",
                    "permission_name": "审核管理",
                    "module": "review",
                    "parent_id": None,
                    "is_menu": True,
                    "icon": "DocumentChecked",
                    "route_path": "review",
                    "sort_order": 4,
                },
                {
                    "permission_code": "review:pending",
                    "permission_name": "待审核",
                    "module": "review",
                    "parent_id": None,
                    "is_menu": True,
                    "route_path": "review/pending",
                    "component_path": "@/views/review/pending.vue",
                    "sort_order": 1,
                },
                {
                    "permission_code": "review:approved",
                    "permission_name": "已通过",
                    "module": "review",
                    "parent_id": None,
                    "is_menu": True,
                    "route_path": "review/approved",
                    "component_path": "@/views/review/approved.vue",
                    "sort_order": 2,
                },
                {
                    "permission_code": "review:approve",
                    "permission_name": "通过审核",
                    "module": "review",
                    "parent_id": None,
                    "is_menu": False,
                    "sort_order": 10,
                },
                {
                    "permission_code": "review:reject",
                    "permission_name": "拒绝审核",
                    "module": "review",
                    "parent_id": None,
                    "is_menu": False,
                    "sort_order": 11,
                },

                # ========== 加分申请 (super_admin, admin, user) ==========
                {
                    "permission_code": "apply",
                    "permission_name": "加分申请",
                    "module": "apply",
                    "parent_id": None,
                    "is_menu": True,
                    "icon": "FolderAdd",
                    "route_path": "apply",
                    "sort_order": 1,
                },
                {
                    "permission_code": "apply:create",
                    "permission_name": "提交申请",
                    "module": "apply",
                    "parent_id": None,
                    "is_menu": True,
                    "route_path": "apply/create",
                    "component_path": "@/views/apply/create.vue",
                    "sort_order": 1,
                },
                {
                    "permission_code": "apply:my",
                    "permission_name": "我的申请",
                    "module": "apply",
                    "parent_id": None,
                    "is_menu": True,
                    "route_path": "apply/my",
                    "component_path": "@/views/apply/my.vue",
                    "sort_order": 2,
                },
                {
                    "permission_code": "apply:view",
                    "permission_name": "查看申请详情",
                    "module": "apply",
                    "parent_id": None,
                    "is_menu": False,
                    "sort_order": 3,
                },
            ]

            created_permissions = {}
            for perm_data in permissions_data:
                # 映射旧字段名到新字段名
                mapped_data = {
                    "code": perm_data["permission_code"],
                    "name": perm_data["permission_name"],
                    "route_path": perm_data.get("route_path"),
                    "description": None,
                    "sort_order": perm_data.get("sort_order", 0),
                    "status": True,
                    "parent_id": None,
                }

                result = await db.execute(
                    select(Permission).where(Permission.code == mapped_data["code"])
                )
                existing_perm = result.scalar_one_or_none()

                if existing_perm:
                    print(f"[跳过] 权限已存在: {perm_data['permission_code']}")
                    created_permissions[perm_data["permission_code"]] = existing_perm
                else:
                    permission = Permission(**mapped_data)
                    db.add(permission)
                    await db.flush()
                    created_permissions[perm_data["permission_code"]] = permission
                    print(f"[创建] 权限: {perm_data['permission_code']}")

            await db.flush()

            # ========== 3. 更新 parent_id ==========
            parent_mapping = {
                "account:view": "account",
                "account:create": "account",
                "account:edit": "account",
                "account:delete": "account",
                "account:assign_role": "account",
                "account:role_manage": "account",
                "account:permission_manage": "account",
                "system_config:view": "system_config",
                "system_config:agent": "system_config",
                "system_config:smtp": "system_config",
                "system_config:edit": "system_config",
                "template:view": "template",
                "template:create": "template",
                "template:edit": "template",
                "template:delete": "template",
                "student:view": "student",
                "student:edit": "student",
                "review:pending": "review",
                "review:approved": "review",
                "apply:create": "apply",
                "apply:my": "apply",
                "apply:view": "apply",
            }

            for child_code, parent_code in parent_mapping.items():
                if child_code in created_permissions and parent_code in created_permissions:
                    child_perm = created_permissions[child_code]
                    parent_perm = created_permissions[parent_code]
                    if child_perm.parent_id is None:
                        child_perm.parent_id = parent_perm.id
                        print(f"[更新] {child_code} 的 parent_id -> {parent_code}")

            await db.commit()

            # ========== 4. 分配权限 ==========

            # super_admin: 全部权限
            super_admin_role = created_roles.get("super_admin")
            super_admin_perms = [
                created_permissions.get("admin:login"),
                created_permissions.get("account:view"),
                created_permissions.get("account:create"),
                created_permissions.get("account:edit"),
                created_permissions.get("account:delete"),
                created_permissions.get("account:assign_role"),
                created_permissions.get("account:role_manage"),
                created_permissions.get("account:permission_manage"),
                created_permissions.get("system_config:view"),
                created_permissions.get("system_config:agent"),
                created_permissions.get("system_config:smtp"),
                created_permissions.get("system_config:edit"),
                created_permissions.get("template:view"),
                created_permissions.get("template:create"),
                created_permissions.get("template:edit"),
                created_permissions.get("template:delete"),
                created_permissions.get("student:view"),
                created_permissions.get("student:edit"),
                created_permissions.get("review:pending"),
                created_permissions.get("review:approved"),
                created_permissions.get("review:approve"),
                created_permissions.get("review:reject"),
                created_permissions.get("apply:create"),
                created_permissions.get("apply:my"),
                created_permissions.get("apply:view"),
            ]

            for perm in super_admin_perms:
                if perm and perm.id:
                    result = await db.execute(
                        select(RolePermission)
                        .where(RolePermission.role_id == super_admin_role.id)
                        .where(RolePermission.permission_id == perm.id)
                    )
                    if not result.scalar_one_or_none():
                        rp = RolePermission(role_id=super_admin_role.id, permission_id=perm.id)
                        db.add(rp)
                        print(f"[分配] super_admin -> {perm.code}")

            # admin: 模板、学生、审核管理（不含账户和系统配置）
            admin_role = created_roles.get("admin")
            admin_perms = [
                created_permissions.get("admin:login"),
                created_permissions.get("template:view"),
                created_permissions.get("template:create"),
                created_permissions.get("template:edit"),
                created_permissions.get("template:delete"),
                created_permissions.get("student:view"),
                created_permissions.get("student:edit"),
                created_permissions.get("review:pending"),
                created_permissions.get("review:approved"),
                created_permissions.get("review:approve"),
                created_permissions.get("review:reject"),
                created_permissions.get("apply:create"),
                created_permissions.get("apply:my"),
                created_permissions.get("apply:view"),
            ]

            for perm in admin_perms:
                if perm and perm.id:
                    result = await db.execute(
                        select(RolePermission)
                        .where(RolePermission.role_id == admin_role.id)
                        .where(RolePermission.permission_id == perm.id)
                    )
                    if not result.scalar_one_or_none():
                        rp = RolePermission(role_id=admin_role.id, permission_id=perm.id)
                        db.add(rp)
                        print(f"[分配] admin -> {perm.code}")

            # reviewer: 审核功能
            reviewer_role = created_roles.get("reviewer")
            reviewer_perms = [
                created_permissions.get("student:view"),
                created_permissions.get("review:pending"),
                created_permissions.get("review:approved"),
                created_permissions.get("review:approve"),
                created_permissions.get("review:reject"),
                created_permissions.get("apply:view"),
            ]

            for perm in reviewer_perms:
                if perm and perm.id:
                    result = await db.execute(
                        select(RolePermission)
                        .where(RolePermission.role_id == reviewer_role.id)
                        .where(RolePermission.permission_id == perm.id)
                    )
                    if not result.scalar_one_or_none():
                        rp = RolePermission(role_id=reviewer_role.id, permission_id=perm.id)
                        db.add(rp)
                        print(f"[分配] reviewer -> {perm.code}")

            # user: 申请权限
            user_role = created_roles.get("user")
            user_perms = [
                created_permissions.get("apply:create"),
                created_permissions.get("apply:my"),
                created_permissions.get("apply:view"),
            ]

            for perm in user_perms:
                if perm and perm.id:
                    result = await db.execute(
                        select(RolePermission)
                        .where(RolePermission.role_id == user_role.id)
                        .where(RolePermission.permission_id == perm.id)
                    )
                    if not result.scalar_one_or_none():
                        rp = RolePermission(role_id=user_role.id, permission_id=perm.id)
                        db.add(rp)
                        print(f"[分配] user -> {perm.permission_code}")

            await db.commit()

            print("\n" + "=" * 50)
            print("[完成] RBAC v2 数据初始化完成")
            print("=" * 50)
            print("角色层级:")
            print("  - SYSTEM_ACCOUNTS (zch): 隐藏顶层白名单，内部机制返回全部权限")
            print("  - super_admin: 超级管理员，账户管理+系统配置+全部业务功能")
            print("  - admin: 管理员，模板+学生+审核管理（无账户/系统配置）")
            print("  - reviewer: 审核员，审核功能")
            print("  - user: 学生，申请功能（注册自动分配）")
            print("=" * 50)

        except Exception as e:
            await db.rollback()
            print(f"[错误] 初始化失败: {e}")
            import traceback
            traceback.print_exc()
            raise


if __name__ == "__main__":
    print("=" * 50)
    print("RBAC v2 数据初始化")
    print("=" * 50)
    asyncio.run(init_rbac_data())
