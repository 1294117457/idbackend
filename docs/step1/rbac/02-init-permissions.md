# Permission 初始化 + 4 角色权限矩阵

> 本文档给出：
> 1. 完整 `PERMISSIONS_DATA`（每条 `permission_code` 对应的 `api_path`）
> 2. 完整 `ROLE_PERMISSIONS`（每个角色拥有哪些 `permission_code`）

---

## 1. PERMISSIONS_DATA（70+ 条）

> 写入 `init_rbac_data.py` 的 `PERMISSIONS_DATA`。
> 格式：`(permission_code, permission_name, api_path, group_code, group_name, sort_order)`

### 1.1 auth（2 条）

```python
# auth
("auth:login",            "用户登录",       "/api/authserver/login",          "auth", "认证", 1),
("auth:admin_login",      "管理员登录",     "/api/authserver/admin/login",    "auth", "认证", 2),
```

> ⚠️ 这两个权限码**没绑到任何中间件路径**（因为 admin/login 已经是白名单），
> 但保留在 DB 里供前端按钮级控制 + 未来可能要把 admin/login 也接入中间件。

### 1.2 user（管理端 7 条 + 学生端 4 条）

```python
# user 管理端
("user:read",             "查看用户列表",   "/api/user/admin/list",                     "user", "用户管理", 10),
("user:create",           "创建用户",       "/api/user/admin/create",                   "user", "用户管理", 11),
("user:batch_create",     "批量创建用户",   "/api/user/admin/batch-create",             "user", "用户管理", 12),
("user:update",           "修改用户状态",   "/api/user/admin/{user_id}/status",         "user", "用户管理", 13),
("user:delete",           "删除用户",       "/api/user/admin/{user_id}",                "user", "用户管理", 14),
("user:assign_role",      "分配用户角色",   "/api/user/{user_id}/roles",                "user", "用户管理", 15),
("user:read_other",       "查看他人角色",   "/api/user/{user_id}/roles",                "user", "用户管理", 16),

# user 学生端
("user:read_self",        "查看自己信息",   "/api/users/me",                            "user", "用户管理", 20),
("user:update_self",      "修改自己信息",   "/api/users/me",                            "user", "用户管理", 21),
("user:update_extra",     "修改扩展信息",   "/api/users/me/extra-info",                 "user", "用户管理", 22),
("user:read_my_roles",    "查看我的角色",   "/api/user/me/roles",                       "user", "用户管理", 23),
```

### 1.3 application（14 条）

```python
# application 学生端
("application:create",    "保存草稿",       "/api/applications/draft",                  "application", "加分申请", 30),
("application:update",    "修改草稿",       "/api/applications/{id}/draft",             "application", "加分申请", 31),
("application:cancel",    "取消申请",       "/api/applications/{id}/cancel",            "application", "加分申请", 32),
("application:submit",    "提交申请",       "/api/applications/{id}/submit",            "application", "加分申请", 33),
("application:submit",    "重新提交",       "/api/applications/{id}/resubmit",          "application", "加分申请", 34),
("application:read",      "我的申请列表",   "/api/applications",                        "application", "加分申请", 35),
("application:read",      "申请详情",       "/api/applications/{id}",                   "application", "加分申请", 36),

# application 审核员端
("application:read",      "待审核列表",     "/api/admin/applications",                  "application", "加分申请", 37),
("application:read",      "审核历史",       "/api/admin/applications/history",          "application", "加分申请", 38),
("application:read",      "我的审核历史",   "/api/admin/applications/my-history",       "application", "加分申请", 39),
("application:proof_review", "审核证明材料", "/api/applications/{id}/proofs/{pid}/review","application", "加分申请", 40),
("application:approve",   "通过申请",       "/api/applications/{id}/pass",              "application", "加分申请", 41),
("application:reject",    "驳回申请",       "/api/applications/{id}/reject",            "application", "加分申请", 42),
("application:revoke",    "撤回已通过申请", "/api/admin/applications/{id}/revoke",      "application", "加分申请", 43),
```

### 1.4 score（4 条）

```python
# score 学生端
("score:read_self",       "查看自己成绩",   "/api/score/me",                            "score", "成绩管理", 50),
("score:recalc_self",     "重算自己成绩",   "/api/score/recalculate",                   "score", "成绩管理", 51),

# score 管理端
("score:recalc_user",     "单用户重算",     "/api/score/recalculate-by-admin",          "score", "成绩管理", 52),
("score:recalc_all",      "全量重算",       "/api/score/recalculate-all",               "score", "成绩管理", 53),
```

### 1.5 template（8 条）+ template_category（7 条）

```python
# template 主表
("template:list",         "模板列表",       "/api/bonus-template/list",                 "template", "模板管理", 60),
("template:list",         "按分类列模板",   "/api/bonus-template/by-category",          "template", "模板管理", 61),
("template:detail",       "模板详情",       "/api/bonus-template/{id}",                 "template", "模板管理", 62),
("template:create",       "创建模板",       "/api/bonus-template",                      "template", "模板管理", 63),
("template:update",       "修改模板",       "/api/bonus-template/{id}",                 "template", "模板管理", 64),
("template:delete",       "删除模板",       "/api/bonus-template/{id}",                 "template", "模板管理", 65),
("template:bind_rule",    "绑定规则",       "/api/bonus-template/{id}/rules",           "template", "模板管理", 66),
("template:unbind_rule",  "解绑规则",       "/api/bonus-template/{id}/rules/{rule_id}", "template", "模板管理", 67),

# template_category
("template:list",         "叶子分类",       "/api/template-category/leaf",              "template", "模板管理", 70),
("template_category:list",  "分类列表",      "/api/template-category/list",              "template", "模板管理", 71),
("template_category:detail","分类详情",      "/api/template-category/{id}",              "template", "模板管理", 72),
("template_category:detail","删除预览",      "/api/template-category/{id}/delete-preview","template","模板管理", 73),
("template_category:create","创建分类",      "/api/template-category",                   "template", "模板管理", 74),
("template_category:update","修改分类",      "/api/template-category/{id}",              "template", "模板管理", 75),
("template_category:delete","删除分类",      "/api/template-category/{id}",              "template", "模板管理", 76),
```

> **设计点**：`/api/template-category/leaf`（学生端选模板用）绑 `template:list` 而不是 `template_category:list`，
> 这样所有登录用户（包括 user）都能进。

### 1.6 rule（12 条，含 attribute 复用）

```python
# rule
("rule:list",             "规则列表",       "/api/rule/list",                           "rule", "规则管理", 80),
("rule:detail",           "规则详情",       "/api/rule/{id}",                           "rule", "规则管理", 81),
("rule:create",           "创建规则",       "/api/rule",                                "rule", "规则管理", 82),
("rule:update",           "修改规则",       "/api/rule/{id}",                           "rule", "规则管理", 83),
("rule:delete",           "删除规则",       "/api/rule/{id}",                           "rule", "规则管理", 84),
("rule:bind_attribute",   "绑定属性",       "/api/rule/{id}/attributes",                "rule", "规则管理", 85),
("rule:unbind_attribute", "解绑属性",       "/api/rule/{id}/attributes/{attribute_id}", "rule", "规则管理", 86),

# attribute（复用 rule 权限码，因为是 rule 的子资源）
("rule:list",             "属性列表",       "/api/rule-attribute/list",                 "rule", "规则管理", 87),
("rule:detail",           "属性详情",       "/api/rule-attribute/{id}",                 "rule", "规则管理", 88),
("rule:create",           "创建属性",       "/api/rule-attribute",                      "rule", "规则管理", 89),
("rule:update",           "修改属性",       "/api/rule-attribute/{id}",                 "rule", "规则管理", 90),
("rule:delete",           "删除属性",       "/api/rule-attribute/{id}",                 "rule", "规则管理", 91),
```

### 1.7 extra_info（6 条）

```python
("extra_info:list",       "字段列表",       "/api/extra-info-field/list",               "extra_info", "扩展字段", 100),
("extra_info:list",       "已启用字段",     "/api/extra-info-field/active",             "extra_info", "扩展字段", 101),
("extra_info:detail",     "字段详情",       "/api/extra-info-field/{id}",               "extra_info", "扩展字段", 102),
("extra_info:create",     "创建字段",       "/api/extra-info-field",                    "extra_info", "扩展字段", 103),
("extra_info:update",     "修改字段",       "/api/extra-info-field/{id}",               "extra_info", "扩展字段", 104),
("extra_info:delete",     "删除字段",       "/api/extra-info-field/{id}",               "extra_info", "扩展字段", 105),
```

### 1.8 file（7 条）

```python
("file:upload",           "上传文件",       "/api/file/upload",                         "file", "文件管理", 110),
("file:upload",           "上传头像",       "/api/file/avatar",                         "file", "文件管理", 111),
("file:list",             "文件搜索",       "/api/file/search",                         "file", "文件管理", 112),
("file:detail",           "文件元信息",     "/api/file/{id}",                           "file", "文件管理", 113),
("file:preview",          "预览链接",       "/api/file/{id}/preview",                   "file", "文件管理", 114),
("file:download",         "下载文件",       "/api/file/{id}/download",                  "file", "文件管理", 115),
("file:update",           "更新文件",       "/api/file/{id}",                           "file", "文件管理", 116),
("file:delete",           "删除文件",       "/api/file/{id}",                           "file", "文件管理", 117),
```

### 1.9 rbac 管理（12 条）

```python
# role 管理
("role:list",             "角色列表",       "/api/system/role/list",                    "rbac", "权限管理", 120),
("role:detail",           "角色详情",       "/api/system/role/{id}",                    "rbac", "权限管理", 121),
("role:detail",           "角色权限",       "/api/system/role/{id}/permissions",        "rbac", "权限管理", 122),
("role:create",           "创建角色",       "/api/system/role/create",                  "rbac", "权限管理", 123),
("role:update",           "更新角色",       "/api/system/role/update",                  "rbac", "权限管理", 124),
("role:delete",           "删除角色",       "/api/system/role/{id}",                    "rbac", "权限管理", 125),
("role:assign_permission", "分配权限给角色", "/api/system/role/assignPermissions",       "rbac", "权限管理", 126),

# permission 管理
("permission:list",       "权限列表",       "/api/system/permission/list",              "rbac", "权限管理", 127),
("permission:list",       "接口扫描",       "/api/system/permission/interfaces",        "rbac", "权限管理", 128),
("permission:create",     "创建权限",       "/api/system/permission/create",            "rbac", "权限管理", 129),
("permission:update",     "更新权限",       "/api/system/permission/update",            "rbac", "权限管理", 130),
("permission:delete",     "删除权限",       "/api/system/permission/{id}",              "rbac", "权限管理", 131),
```

### 1.10 system_config（5 条）

```python
("system_config:read",    "查看系统配置",   "/api/system/config",                       "system", "系统管理", 140),
("system_config:read",    "查看 Agent",     "/api/system/config/agent",                 "system", "系统管理", 141),
("system_config:read",    "查看 SMTP",      "/api/system/config/smtp",                  "system", "系统管理", 142),
("system_config:update",  "修改 Agent",     "/api/system/config/agent",                 "system", "系统管理", 143),
("system_config:update",  "修改 SMTP",      "/api/system/config/smtp",                  "system", "系统管理", 144),
```

---

## 2. ROLE_PERMISSIONS（4 角色 × 权限码）

> 写入 `init_rbac_data.py` 的 `ROLE_PERMISSIONS`。
> key 是 `role_code`，value 是 `permission_code` 列表。

```python
ROLE_PERMISSIONS = {
    # ====================================================
    # super_admin：空列表——PermissionMiddleware 角色短路返回 ["*"]
    # 不需要在 role_permission 表里绑全部权限码（中间件第 80-87 行判断）
    # 加新权限时不用同步更新这里
    # ====================================================
    "super_admin": [],

    # ====================================================
    # admin：业务全权（不含 rbac、不含 system_config）

    # ====================================================
    "admin": [
        "auth:admin_login",
        # user 管理端（不含 create / delete / assign_role）
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

    # ====================================================
    # reviewer：只读 + 审核（无 revoke、无任何写权限）
    # ====================================================
    "reviewer": [
        "auth:admin_login",
        # 仅自己账户
        "user:read_self", "user:update_self",
        "user:read_my_roles",
        # 审核相关（read 全部 + approve/reject/proof_review）
        "application:read",
        "application:proof_review", "application:approve",
        "application:reject",
        # 自己的成绩
        "score:read_self",
        # 看模板
        "template:list", "template:detail",
        # 看分类（leaf 给所有人，list 也给个方便查找）
        "template_category:list",
        # 看证明材料
        "file:list", "file:detail", "file:preview", "file:download",
    ],

    # ====================================================
    # user：仅自己
    # ====================================================
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
        # 看模板（提交申请用）
        "template:list", "template:detail",
        # 上传 / 查看自己的证明材料
        "file:upload", "file:list", "file:detail",
        "file:preview", "file:download",
    ],
}
```

---

## 3. 权限数量核对

| 角色 | 权限码数量 | 范围 |
|------|----------|------|
| `super_admin` | 0 | 全部（中间件角色短路，非绑定） |
| `admin` | 51 | 业务全部（不含 rbac、不含 system_config）|
| `reviewer` | 16 | 只读 + 审核 |
| `user` | 18 | 仅自己 |

> ⚠️ user 比 reviewer 多的原因：user 有 `application:create/update/cancel/submit` 这些"对自己"的操作。
> 业务上"create"等于"学生自己存草稿"，不是"为他人创建"——权限码名字可能误导，但中间件只挡角色不挡数据。
> Service 层用 `user_id == current_user_id` 进一步校验"只能操作自己"。

---

## 4. 关键设计取舍（Q&A）

### Q1：为什么 `admin` 没有 `user:create` / `user:delete` / `user:assign_role`？

A：admin 是"业务运营"，不是"账户管理员"。

- `user:create` / `user:delete`：通常由 super_admin 做（注册季一次性批量建账号）
- `user:assign_role`：admin 不应该能把自己升为 super_admin（防"造反"）

### Q2：为什么 `admin` 没有 `role:*` / `permission:*`？

A：admin 不能管 RBAC——理由同上。

- admin 误删 role / 改 permission.api_path 会导致全站不可用
- 只有 super_admin 能动 RBAC

### Q3：为什么 `reviewer` 没有 `application:revoke`？

A：`revoke` 是把"已通过"的申请撤销，属于**事后追责**，比"审核"严肃。

- reviewer 撤销别人通过的申请 → 政治风险
- 必须由 super_admin / admin 操作

### Q4：为什么 `reviewer` 没有任何"写"权限？

A：reviewer 是"评委"角色。
- 审核（approve/reject/proof_review）算"写"，但这是**业务动作**，不是"管理写"
- 任何"模板/规则/分类/用户"的写权限一律不给

### Q5：为什么 user 没有 `user:read`（管理端用户列表）？

A：学生不应该能看到其他学生的列表（隐私）。
- 只有 admin/super_admin 看用户列表
- user 角色用 `user:read_self` 只能看自己

### Q6：为什么 user 有 `application:create`？

A：`application:create` 的语义是"保存草稿"，**业务上等于"学生给自己存草稿"**。
中间件只挡"无权限角色"，不区分"自己"和"别人"。
Service 层有 `user_id == current_user_id` 的校验，所以即使别人拿到 token 也写不进别人名下。

---

## 5. 校验 SQL

```sql
-- 1. 各角色权限数
SELECT r.role_code, COUNT(rp.permission_id) AS perm_count
FROM role r
LEFT JOIN role_permission rp ON rp.role_id = r.id
GROUP BY r.id, r.role_code
ORDER BY r.sort_order;
-- 期望：super_admin=0, admin=51, reviewer=16, user=18

-- 2. 各分组权限数
SELECT group_code, group_name, COUNT(*) AS cnt
FROM permission
GROUP BY group_code, group_name
ORDER BY group_code;
-- 期望：auth=2, user=11, application=14, score=4,
--       template=15, rule=12, extra_info=6, file=8, rbac=12, system=5
--       template=15, rule=12, extra_info=6, file=8, rbac=12, system=5

-- 3. 权限总数
SELECT COUNT(*) FROM permission;
-- 期望：~70+（具体数字看你选的命名规则）

-- 4. user 角色具体有什么权限
SELECT p.permission_code, p.api_path
FROM permission p
JOIN role_permission rp ON rp.permission_id = p.id
JOIN role r ON r.id = rp.role_id
WHERE r.role_code = 'user'
ORDER BY p.sort_order;

-- 5. 检查"哪些 API 没绑权限码"（应当为空）
SELECT DISTINCT api_path
FROM permission
WHERE api_path IS NULL
   OR api_path NOT LIKE '/api/%';
```