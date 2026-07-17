# init_rbac_data.py · 完整可执行版

> 直接用本文件**整文件替换** `src/scripts/init_rbac_data.py` 的内容，然后跑：
> ```bash
> python -m src.scripts.init_rbac_data
> ```

---

## 完整代码

```python
"""RBAC 初始化数据脚本 v3

运行：
    cd /home/dustp/codes/idproject/idbackend
    python -m src.scripts.init_rbac_data

详见 docs/rbac/02-init-permissions.md
"""
import asyncio
import os
import sys

from sqlalchemy import select, delete

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.infra.database import AsyncSessionLocal
from src.models.user import Permission, Role, RolePermission


# ============ 4 个系统角色 ============

ROLES_DATA = [
    {
        "role_code": "super_admin",
        "role_name": "超级管理员",
        "description": "全权：可管理账户、角色、权限、系统配置，含全部业务功能",
        "sort_order": 1,
        "is_system": True,
    },
    {
        "role_code": "admin",
        "role_name": "管理员",
        "description": "业务运营：模板/规则/学生/审核/成绩，不能管 RBAC 和系统配置",
        "sort_order": 2,
        "is_system": True,
    },
    {
        "role_code": "reviewer",
        "role_name": "审核员",
        "description": "审核学生申请（pass/reject），无 revoke、无写权限",
        "sort_order": 3,
        "is_system": True,
    },
    {
        "role_code": "user",
        "role_name": "学生",
        "description": "普通学生：提交加分申请、维护自己资料、看自己的成绩",
        "sort_order": 4,
        "is_system": True,
    },
]


# ============ 权限码 ============
# 格式：(permission_code, permission_name, api_path, group_code, group_name, sort_order)

PERMISSIONS_DATA = [
    # ===== auth =====
    ("auth:login",            "用户登录",       "/api/authserver/login",          "auth", "认证", 1),
    ("auth:admin_login",      "管理员登录",     "/api/authserver/admin/login",    "auth", "认证", 2),

    # ===== user 管理端 =====
    ("user:read",             "查看用户列表",   "/api/user/admin/list",                     "user", "用户管理", 10),
    ("user:create",           "创建用户",       "/api/user/admin/create",                   "user", "用户管理", 11),
    ("user:batch_create",     "批量创建用户",   "/api/user/admin/batch-create",             "user", "用户管理", 12),
    ("user:update",           "修改用户状态",   "/api/user/admin/{user_id}/status",         "user", "用户管理", 13),
    ("user:delete",           "删除用户",       "/api/user/admin/{user_id}",                "user", "用户管理", 14),
    ("user:assign_role",      "分配用户角色",   "/api/user/{user_id}/roles",                "user", "用户管理", 15),
    ("user:read_other",       "查看他人角色",   "/api/user/{user_id}/roles",                "user", "用户管理", 16),

    # ===== user 学生端 =====
    ("user:read_self",        "查看自己信息",   "/api/users/me",                            "user", "用户管理", 20),
    ("user:update_self",      "修改自己信息",   "/api/users/me",                            "user", "用户管理", 21),
    ("user:update_extra",     "修改扩展信息",   "/api/users/me/extra-info",                 "user", "用户管理", 22),
    ("user:read_my_roles",    "查看我的角色",   "/api/user/me/roles",                       "user", "用户管理", 23),

    # ===== application 学生端 =====
    ("application:create",    "保存草稿",       "/api/applications/draft",                  "application", "加分申请", 30),
    ("application:update",    "修改草稿",       "/api/applications/{id}/draft",             "application", "加分申请", 31),
    ("application:cancel",    "取消申请",       "/api/applications/{id}/cancel",            "application", "加分申请", 32),
    ("application:submit",    "提交申请",       "/api/applications/{id}/submit",            "application", "加分申请", 33),
    ("application:submit",    "重新提交",       "/api/applications/{id}/resubmit",          "application", "加分申请", 34),
    ("application:read",      "我的申请列表",   "/api/applications",                        "application", "加分申请", 35),
    ("application:read",      "申请详情",       "/api/applications/{id}",                   "application", "加分申请", 36),

    # ===== application 审核员端 =====
    ("application:read",      "待审核列表",     "/api/admin/applications",                  "application", "加分申请", 37),
    ("application:read",      "审核历史",       "/api/admin/applications/history",          "application", "加分申请", 38),
    ("application:read",      "我的审核历史",   "/api/admin/applications/my-history",       "application", "加分申请", 39),
    ("application:proof_review", "审核证明材料", "/api/applications/{id}/proofs/{pid}/review","application", "加分申请", 40),
    ("application:approve",   "通过申请",       "/api/applications/{id}/pass",              "application", "加分申请", 41),
    ("application:reject",    "驳回申请",       "/api/applications/{id}/reject",            "application", "加分申请", 42),
    ("application:revoke",    "撤回已通过申请", "/api/admin/applications/{id}/revoke",      "application", "加分申请", 43),

    # ===== score =====
    ("score:read_self",       "查看自己成绩",   "/api/score/me",                            "score", "成绩管理", 50),
    ("score:recalc_self",     "重算自己成绩",   "/api/score/recalculate",                   "score", "成绩管理", 51),
    ("score:recalc_user",     "单用户重算",     "/api/score/recalculate-by-admin",          "score", "成绩管理", 52),
    ("score:recalc_all",      "全量重算",       "/api/score/recalculate-all",               "score", "成绩管理", 53),

    # ===== template 主表 =====
    ("template:list",         "模板列表",       "/api/bonus-template/list",                 "template", "模板管理", 60),
    ("template:list",         "按分类列模板",   "/api/bonus-template/by-category",          "template", "模板管理", 61),
    ("template:detail",       "模板详情",       "/api/bonus-template/{id}",                 "template", "模板管理", 62),
    ("template:create",       "创建模板",       "/api/bonus-template",                      "template", "模板管理", 63),
    ("template:update",       "修改模板",       "/api/bonus-template/{id}",                 "template", "模板管理", 64),
    ("template:delete",       "删除模板",       "/api/bonus-template/{id}",                 "template", "模板管理", 65),
    ("template:bind_rule",    "绑定规则",       "/api/bonus-template/{id}/rules",           "template", "模板管理", 66),
    ("template:unbind_rule",  "解绑规则",       "/api/bonus-template/{id}/rules/{rule_id}", "template", "模板管理", 67),

    # ===== template_category =====
    ("template:list",         "叶子分类",       "/api/template-category/leaf",              "template", "模板管理", 70),
    ("template_category:list",  "分类列表",      "/api/template-category/list",              "template", "模板管理", 71),
    ("template_category:detail","分类详情",      "/api/template-category/{id}",              "template", "模板管理", 72),
    ("template_category:detail","删除预览",      "/api/template-category/{id}/delete-preview","template", "模板管理", 73),
    ("template_category:create","创建分类",      "/api/template-category",                   "template", "模板管理", 74),
    ("template_category:update","修改分类",      "/api/template-category/{id}",              "template", "模板管理", 75),
    ("template_category:delete","删除分类",      "/api/template-category/{id}",              "template", "模板管理", 76),

    # ===== rule =====
    ("rule:list",             "规则列表",       "/api/rule/list",                           "rule", "规则管理", 80),
    ("rule:detail",           "规则详情",       "/api/rule/{id}",                           "rule", "规则管理", 81),
    ("rule:create",           "创建规则",       "/api/rule",                                "rule", "规则管理", 82),
    ("rule:update",           "修改规则",       "/api/rule/{id}",                           "rule", "规则管理", 83),
    ("rule:delete",           "删除规则",       "/api/rule/{id}",                           "rule", "规则管理", 84),
    ("rule:bind_attribute",   "绑定属性",       "/api/rule/{id}/attributes",                "rule", "规则管理", 85),
    ("rule:unbind_attribute", "解绑属性",       "/api/rule/{id}/attributes/{attribute_id}", "rule", "规则管理", 86),

    # ===== attribute（复用 rule 权限码） =====
    ("rule:list",             "属性列表",       "/api/rule-attribute/list",                 "rule", "规则管理", 87),
    ("rule:detail",           "属性详情",       "/api/rule-attribute/{id}",                 "rule", "规则管理", 88),
    ("rule:create",           "创建属性",       "/api/rule-attribute",                      "rule", "规则管理", 89),
    ("rule:update",           "修改属性",       "/api/rule-attribute/{id}",                 "rule", "规则管理", 90),
    ("rule:delete",           "删除属性",       "/api/rule-attribute/{id}",                 "rule", "规则管理", 91),

    # ===== extra_info_field =====
    ("extra_info:list",       "字段列表",       "/api/extra-info-field/list",               "extra_info", "扩展字段", 100),
    ("extra_info:list",       "已启用字段",     "/api/extra-info-field/active",             "extra_info", "扩展字段", 101),
    ("extra_info:detail",     "字段详情",       "/api/extra-info-field/{id}",               "extra_info", "扩展字段", 102),
    ("extra_info:create",     "创建字段",       "/api/extra-info-field",                    "extra_info", "扩展字段", 103),
    ("extra_info:update",     "修改字段",       "/api/extra-info-field/{id}",               "extra_info", "扩展字段", 104),
    ("extra_info:delete",     "删除字段",       "/api/extra-info-field/{id}",               "extra_info", "扩展字段", 105),

    # ===== file =====
    ("file:upload",           "上传文件",       "/api/file/upload",                         "file", "文件管理", 110),
    ("file:upload",           "上传头像",       "/api/file/avatar",                         "file", "文件管理", 111),
    ("file:list",             "文件搜索",       "/api/file/search",                         "file", "文件管理", 112),
    ("file:detail",           "文件元信息",     "/api/file/{id}",                           "file", "文件管理", 113),
    ("file:preview",          "预览链接",       "/api/file/{id}/preview",                   "file", "文件管理", 114),
    ("file:download",         "下载文件",       "/api/file/{id}/download",                  "file", "文件管理", 115),
    ("file:update",           "更新文件",       "/api/file/{id}",                           "file", "文件管理", 116),
    ("file:delete",           "删除文件",       "/api/file/{id}",                           "file", "文件管理", 117),

    # ===== rbac: role 管理 =====
    ("role:list",             "角色列表",       "/api/system/role/list",                    "rbac", "权限管理", 120),
    ("role:detail",           "角色详情",       "/api/system/role/{id}",                    "rbac", "权限管理", 121),
    ("role:detail",           "角色权限",       "/api/system/role/{id}/permissions",        "rbac", "权限管理", 122),
    ("role:create",           "创建角色",       "/api/system/role/create",                  "rbac", "权限管理", 123),
    ("role:update",           "更新角色",       "/api/system/role/update",                  "rbac", "权限管理", 124),
    ("role:delete",           "删除角色",       "/api/system/role/{id}",                    "rbac", "权限管理", 125),
    ("role:assign_permission", "分配权限给角色", "/api/system/role/assignPermissions",       "rbac", "权限管理", 126),

    # ===== rbac: permission 管理 =====
    ("permission:list",       "权限列表",       "/api/system/permission/list",              "rbac", "权限管理", 127),
    ("permission:list",       "接口扫描",       "/api/system/permission/interfaces",        "rbac", "权限管理", 128),
    ("permission:create",     "创建权限",       "/api/system/permission/create",            "rbac", "权限管理", 129),
    ("permission:update",     "更新权限",       "/api/system/permission/update",            "rbac", "权限管理", 130),
    ("permission:delete",     "删除权限",       "/api/system/permission/{id}",              "rbac", "权限管理", 131),

    # ===== system_config =====
    ("system_config:read",    "查看系统配置",   "/api/system/config",                       "system", "系统管理", 140),
    ("system_config:read",    "查看 Agent",     "/api/system/config/agent",                 "system", "系统管理", 141),
    ("system_config:read",    "查看 SMTP",      "/api/system/config/smtp",                  "system", "系统管理", 142),
    ("system_config:update",  "修改 Agent",     "/api/system/config/agent",                 "system", "系统管理", 143),
    ("system_config:update",  "修改 SMTP",      "/api/system/config/smtp",                  "system", "系统管理", 144),
]


# ============ 4 角色 × 权限码 ============

ROLE_PERMISSIONS = {
    # ============== super_admin：空列表（中间件角色短路返回 ["*"]） ==============
    # 不需要在 role_permission 表里绑全部权限码
    # PermissionMiddleware 第 80-87 行：识别到 roles 含 super_admin 就直接放行
    "super_admin": [],  # 中间件角色短路返回 ["*"]，详见 PermissionMiddleware

    # ============== admin：业务全权（不含 rbac / system） ==============
    "admin": [
        "auth:admin_login",
        # user 管理端（不含 create/delete/assign_role）
        "user:read", "user:update",
        # user 学生端
        "user:read_self", "user:update_self", "user:update_extra",
        "user:read_my_roles",
        # application 全部
        "application:create", "application:update", "application:cancel",
        "application:submit", "application:read",
        "application:proof_review", "application:approve",
        "application:reject", "application:revoke",
        # score
        "score:read_self", "score:recalc_self",
        "score:recalc_user", "score:recalc_all",
        # template 全部
        "template:list", "template:detail",
        "template:create", "template:update", "template:delete",
        "template:bind_rule", "template:unbind_rule",
        # template_category 全部
        "template_category:list", "template_category:detail",
        "template_category:create", "template_category:update",
        "template_category:delete",
        # rule 全部
        "rule:list", "rule:detail",
        "rule:create", "rule:update", "rule:delete",
        "rule:bind_attribute", "rule:unbind_attribute",
        # extra_info 全部
        "extra_info:list", "extra_info:detail",
        "extra_info:create", "extra_info:update", "extra_info:delete",
        # file 全部
        "file:upload", "file:list", "file:detail",
        "file:preview", "file:download",
        "file:update", "file:delete",
    ],

    # ============== reviewer：只读 + 审核（无 revoke、无任何管理写） ==============
    "reviewer": [
        "auth:admin_login",
        # 仅自己账户
        "user:read_self", "user:update_self",
        "user:read_my_roles",
        # 审核相关
        "application:read",
        "application:proof_review", "application:approve",
        "application:reject",
        # 自己的成绩
        "score:read_self",
        # 看模板（理解规则用）
        "template:list", "template:detail",
        # 看分类（找模板用）
        "template_category:list",
        # 看证明材料
        "file:list", "file:detail", "file:preview", "file:download",
    ],

    # ============== user：仅自己 ==============
    "user": [
        # 自己账户
        "user:read_self", "user:update_self", "user:update_extra",
        "user:read_my_roles",
        # 自己申请
        "application:create", "application:update",
        "application:cancel", "application:submit",
        "application:read",
        # 自己成绩
        "score:read_self", "score:recalc_self",
        # 看模板
        "template:list", "template:detail",
        # 上传 / 查看自己的证明
        "file:upload", "file:list", "file:detail",
        "file:preview", "file:download",
    ],
}


# ============ 写入逻辑 ============

async def init_rbac_data():
    async with AsyncSessionLocal() as db:
        try:
            # 1) 写入 4 个 role（已存在则跳过）
            created_roles = {}
            for role_data in ROLES_DATA:
                result = await db.execute(
                    select(Role).where(Role.role_code == role_data["role_code"])
                )
                existing = result.scalar_one_or_none()
                if existing:
                    created_roles[role_data["role_code"]] = existing
                    print(f"[跳过] 角色已存在: {role_data['role_code']}")
                else:
                    role = Role(**role_data, status=True)
                    db.add(role)
                    await db.flush()
                    created_roles[role_data["role_code"]] = role
                    print(f"[创建] 角色: {role_data['role_code']}")

            # 2) 写入权限码（已存在则同步更新 group/api_path，缺则新增）
            created_permissions = {}
            for code, name, api_path, group_code, group_name, sort_order in PERMISSIONS_DATA:
                result = await db.execute(
                    select(Permission).where(Permission.permission_code == code)
                )
                existing = result.scalar_one_or_none()
                if existing:
                    # 同步 group / api_path
                    updated = False
                    if existing.group_code != group_code:
                        existing.group_code = group_code
                        updated = True
                    if existing.group_name != group_name:
                        existing.group_name = group_name
                        updated = True
                    if existing.api_path != api_path:
                        existing.api_path = api_path
                        updated = True
                    if updated:
                        print(f"[更新] 权限: {code}")
                    created_permissions[code] = existing
                else:
                    perm = Permission(
                        permission_code=code,
                        permission_name=name,
                        api_path=api_path,
                        description=name,
                        group_code=group_code,
                        group_name=group_name,
                        sort_order=sort_order,
                        status=True,
                    )
                    db.add(perm)
                    await db.flush()
                    created_permissions[code] = perm
                    print(f"[创建] 权限: {code} → {api_path}")

            await db.flush()

            # 3) 写入 role_permission（先删后建，保证最新矩阵）
            for role_code, perm_codes in ROLE_PERMISSIONS.items():
                role = created_roles.get(role_code)
                if not role:
                    print(f"[警告] 角色不存在，跳过: {role_code}")
                    continue

                # 清掉该角色所有旧绑定
                await db.execute(
                    delete(RolePermission).where(RolePermission.role_id == role.id)
                )

                bound = 0
                for perm_code in perm_codes:
                    perm = created_permissions.get(perm_code)
                    if not perm:
                        print(f"[警告] 权限码未找到: {perm_code}（角色 {role_code}）")
                        continue
                    db.add(RolePermission(role_id=role.id, permission_id=perm.id))
                    bound += 1
                print(f"[绑定] {role_code}: {bound} 条权限")

            await db.commit()

            print("\n" + "=" * 60)
            print("[完成] RBAC 初始化数据已写入")
            print("=" * 60)
            print(f"角色: super_admin / admin / reviewer / user")
            print(f"权限码总数: {len(created_permissions)}")
            print(f"分组: {sorted(set(p[3] for p in PERMISSIONS_DATA))}")
            print("=" * 60)

        except Exception as e:
            await db.rollback()
            print(f"[错误] 初始化失败: {e}")
            import traceback
            traceback.print_exc()
            raise


if __name__ == "__main__":
    print("=" * 60)
    print("RBAC 数据初始化")
    print("=" * 60)
    asyncio.run(init_rbac_data())
```

---

## 跑完后验证

```bash
# 1. 各角色权限数
psql "$DATABASE_URL" <<'EOF'
SELECT r.role_code, COUNT(rp.permission_id) AS perm_count
FROM role r
LEFT JOIN role_permission rp ON rp.role_id = r.id
GROUP BY r.id, r.role_code
ORDER BY r.sort_order;
EOF
```

预期：

| role_code | perm_count |
|-----------|-----------|
| super_admin | 0 |
| admin | 51 |
| reviewer | 16 |
| user | 18 |

如果数字对不上，按 4 个文档的清单对比 `PERMISSIONS_DATA` 长度（~78）和 `ROLE_PERMISSIONS` 各角色列表长度。