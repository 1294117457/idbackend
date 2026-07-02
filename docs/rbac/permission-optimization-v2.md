# RBAC 权限优化方案

> 文档版本: v2.0
> 创建日期: 2026-07-02
> 适用工程: idpython (后端) + idfrontend-admin (前端)

---

## 一、设计原则

### 1.1 双层管理员机制

```
┌─────────────────────────────────────────────────────────┐
│                    SYSTEM_ACCOUNTS (zch)                  │
│                   隐藏的顶层权限白名单                     │
│              自动获取全部权限（内部机制）                   │
│              不在 UI 中显示为可编辑角色                    │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│                      super_admin                         │
│               明面上的超级管理员角色                       │
│    • 账户管理 • 系统配置 • 全部业务功能                     │
│              可在 RBAC 中分配，不限制数量                   │
└─────────────────────────────────────────────────────────┘
                            │
            ┌───────────────┼───────────────┐
            ▼               ▼               ▼
    ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
    │    admin    │ │  reviewer   │ │    user     │
    │ 普通管理员   │ │   审核员    │ │   学生用户   │
    │ 模板/学生   │ │   审核功能   │ │  提交申请   │
    │ 审核管理    │ │             │ │             │
    └─────────────┘ └─────────────┘ └─────────────┘
```

### 1.2 权限等级划分

| 等级 | 角色 | 来源 | 权限范围 |
|------|------|------|----------|
| L0 | SYSTEM_ACCOUNTS (zch) | .env 配置 | **全部权限**（内部机制，不在 UI 暴露） |
| L1 | super_admin | RBAC 角色管理 | 账户管理 + 系统配置 + 全部业务功能 |
| L2 | admin | RBAC 角色管理 | 模板管理 + 学生管理 + 审核管理 |
| L3 | reviewer | RBAC 角色管理 | 审核功能 |
| L4 | user | 注册自动分配 | 提交申请 |

---

## 二、权限矩阵

### 2.1 功能权限对照表

| 功能模块 | 功能点 | SYSTEM_ACCOUNTS | super_admin | admin | reviewer | user |
|---------|--------|:---------------:|:-----------:|:-----:|:--------:|:----:|
| **账户管理** | 账户列表 | 内部 | ✅ | ❌ | ❌ | ❌ |
| | 创建账户 | 内部 | ✅ | ❌ | ❌ | ❌ |
| | 编辑账户 | 内部 | ✅ | ❌ | ❌ | ❌ |
| | 删除账户 | 内部 | ✅ | ❌ | ❌ | ❌ |
| | 分配角色 | 内部 | ✅ | ❌ | ❌ | ❌ |
| **系统配置** | Agent API Key | 内部 | ✅ | ❌ | ❌ | ❌ |
| | SMTP 配置 | 内部 | ✅ | ❌ | ❌ | ❌ |
| | 系统参数 | 内部 | ✅ | ❌ | ❌ | ❌ |
| **模板管理** | 模板列表 | 内部 | ✅ | ✅ | ❌ | ❌ |
| | 创建模板 | 内部 | ✅ | ✅ | ❌ | ❌ |
| | 编辑模板 | 内部 | ✅ | ✅ | ❌ | ❌ |
| | 删除模板 | 内部 | ✅ | ✅ | ❌ | ❌ |
| **学生管理** | 学生列表 | 内部 | ✅ | ✅ | ❌ | ❌ |
| | 查看学生信息 | 内部 | ✅ | ✅ | ❌ | ❌ |
| | 编辑学生信息 | 内部 | ✅ | ✅ | ❌ | ❌ |
| **审核管理** | 待审核列表 | 内部 | ✅ | ✅ | ✅ | ❌ |
| | 审核操作 | 内部 | ✅ | ✅ | ✅ | ❌ |
| | 已审核列表 | 内部 | ✅ | ✅ | ✅ | ❌ |
| **加分申请** | 提交申请 | 内部 | ✅ | ✅ | ❌ | ✅ |
| | 我的申请 | 内部 | ✅ | ✅ | ❌ | ✅ |
| | 申请详情 | 内部 | ✅ | ✅ | ✅ | ✅ |

### 2.2 权限代码设计

```
权限代码格式: <模块>:<操作>

┌─────────────────────────────────────────────┐
│              SYSTEM_ACCOUNTS (内部)           │
│                   无需权限代码                 │
│              直接返回 ["*"] 全部权限             │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│                 super_admin                  │
├─────────────────────────────────────────────┤
│  account:*       账户管理全部                  │
│  system_config:* 系统配置全部                  │
│  template:*      模板管理全部                  │
│  student:*       学生管理全部                  │
│  review:*        审核管理全部                  │
│  apply:*         申请管理全部                  │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│                    admin                     │
├─────────────────────────────────────────────┤
│  template:*      模板管理全部                  │
│  student:view    查看学生                     │
│  student:edit    编辑学生                     │
│  review:*        审核管理全部                  │
│  apply:view      查看申请                     │
│  apply:my        我的申请                     │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│                  reviewer                    │
├─────────────────────────────────────────────┤
│  student:view    查看学生                     │
│  review:pending  待审核                       │
│  review:approved 已通过                      │
│  review:approve  通过审核                     │
│  review:reject   拒绝审核                     │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│                    user                      │
├─────────────────────────────────────────────┤
│  apply:create    提交申请                     │
│  apply:my        我的申请                     │
│  apply:view      查看申请详情                  │
└─────────────────────────────────────────────┘
```

---

## 三、实现方案

### 3.1 角色定义

```python
roles_data = [
    {
        "role_code": "super_admin",
        "role_name": "超级管理员",
        "description": "可管理账户、修改系统配置，拥有全部业务权限",
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
```

### 3.2 权限定义

```python
permissions_data = [
    # ========== 账户管理 (super_admin only) ==========
    {"permission_code": "account", "permission_name": "账户管理", "module": "account", "is_menu": True, "icon": "User", ...},
    {"permission_code": "account:view", "permission_name": "账户列表", ...},
    {"permission_code": "account:create", "permission_name": "创建账户", ...},
    {"permission_code": "account:edit", "permission_name": "编辑账户", ...},
    {"permission_code": "account:delete", "permission_name": "删除账户", ...},
    {"permission_code": "account:assign_role", "permission_name": "分配角色", ...},

    # ========== 系统配置 (super_admin only) ==========
    {"permission_code": "system_config", "permission_name": "系统配置", "module": "system_config", "is_menu": True, "icon": "Setting", ...},
    {"permission_code": "system_config:view", "permission_name": "查看配置", ...},
    {"permission_code": "system_config:agent", "permission_name": "Agent配置", ...},
    {"permission_code": "system_config:smtp", "permission_name": "邮件配置", ...},
    {"permission_code": "system_config:edit", "permission_name": "编辑配置", ...},

    # ========== 模板管理 (super_admin, admin) ==========
    {"permission_code": "template", "permission_name": "模板管理", "module": "template", "is_menu": True, "icon": "Document", ...},
    {"permission_code": "template:view", "permission_name": "查看模板", ...},
    {"permission_code": "template:create", "permission_name": "创建模板", ...},
    {"permission_code": "template:edit", "permission_name": "编辑模板", ...},
    {"permission_code": "template:delete", "permission_name": "删除模板", ...},

    # ========== 学生管理 (super_admin, admin, reviewer) ==========
    {"permission_code": "student", "permission_name": "学生管理", "module": "student", "is_menu": True, "icon": "School", ...},
    {"permission_code": "student:view", "permission_name": "查看学生", ...},
    {"permission_code": "student:edit", "permission_name": "编辑学生", ...},

    # ========== 审核管理 (super_admin, admin, reviewer) ==========
    {"permission_code": "review", "permission_name": "审核管理", "module": "review", "is_menu": True, "icon": "DocumentChecked", ...},
    {"permission_code": "review:pending", "permission_name": "待审核", ...},
    {"permission_code": "review:approved", "permission_name": "已通过", ...},
    {"permission_code": "review:approve", "permission_name": "通过审核", ...},
    {"permission_code": "review:reject", "permission_name": "拒绝审核", ...},

    # ========== 加分申请 (所有人可访问自己) ==========
    {"permission_code": "apply", "permission_name": "加分申请", "module": "apply", "is_menu": True, "icon": "FolderAdd", ...},
    {"permission_code": "apply:create", "permission_name": "提交申请", ...},
    {"permission_code": "apply:my", "permission_name": "我的申请", ...},
    {"permission_code": "apply:view", "permission_name": "查看申请详情", ...},
]
```

### 3.3 角色权限分配

```python
# super_admin: 全部业务权限（不含 SYSTEM_ACCOUNTS 的特殊地位）
super_admin_permissions = [
    "account:*",      # 账户管理
    "system_config:*", # 系统配置
    "template:*",     # 模板管理
    "student:*",      # 学生管理
    "review:*",       # 审核管理
    "apply:*",        # 申请管理
]

# admin: 业务权限（不含账户和系统配置）
admin_permissions = [
    "template:*",     # 模板管理
    "student:view",   # 查看学生
    "student:edit",   # 编辑学生
    "review:*",       # 审核管理
    "apply:view",    # 查看申请
    "apply:my",       # 我的申请
]

# reviewer: 审核权限
reviewer_permissions = [
    "student:view",   # 查看学生
    "review:pending", # 待审核
    "review:approved", # 已通过
    "review:approve", # 通过审核
    "review:reject",  # 拒绝审核
]

# user: 申请权限（注册时自动分配）
user_permissions = [
    "apply:create",   # 提交申请
    "apply:my",      # 我的申请
    "apply:view",    # 查看申请详情
]
```

---

## 四、SYSTEM_ACCOUNTS 特殊处理

### 4.1 设计说明

`SYSTEM_ACCOUNTS` 是隐藏的顶层白名单，用于：
- 防止管理员误删自己导致系统无法管理
- 紧急情况下直接获取全部权限
- 不在 UI 的角色管理中暴露

### 4.2 实现逻辑

```python
# src/services/rbac_service.py

class RbacService:
    @staticmethod
    async def get_user_permissions(db: AsyncSession, user_id: int) -> List[str]:
        """
        获取用户权限列表

        优先级：
        1. SYSTEM_ACCOUNTS 白名单用户 → 返回 ["*"]（内部机制）
        2. 其他用户 → 根据角色分配的标准 RBAC
        """
        user = await db.get(User, user_id)
        if not user:
            return []

        # 【关键】SYSTEM_ACCOUNTS 白名单，直接返回全部权限
        if RbacService._is_admin(user.username):
            return ["*"]  # 内部机制，UI 中不显示

        # 普通用户：标准 RBAC
        # ... 查询角色权限 ...
```

### 4.3 安全考虑

| 措施 | 说明 |
|------|------|
| 日志记录 | 对 SYSTEM_ACCOUNTS 用户的敏感操作记录详细日志 |
| 操作审计 | 账户操作记录到审计表 |
| IP 限制 | 可选的 IP 白名单（可选功能） |

---

## 五、前端适配

### 5.1 路由权限配置

```typescript
// src/router/modules/account-manage.ts
export default {
  path: 'activity',
  meta: {
    title: '账户管理',
    icon: SettingIcon,
    sort: 5,
    requiresPermission: 'account:view',  // super_admin
  },
  // ...
}

// src/router/modules/system-config.ts (新建)
export default {
  path: 'system-config',
  meta: {
    title: '系统配置',
    icon: SettingIcon,
    sort: 99,  // 放在最后
    requiresPermission: 'system_config:view',  // super_admin
  },
}
```

### 5.2 权限检查

```typescript
// src/stores/permission.ts
const hasPermission = (permission: string | string[]): boolean => {
  // ["*"] 表示全部权限
  if (permissions.value.includes('*')) return true

  const perms = Array.isArray(permission) ? permission : [permission]
  return perms.some(p => permissions.value.includes(p))
}
```

### 5.3 UI 隐藏

```vue
<!-- 仅 super_admin 可见 -->
<el-button v-if="hasPermission('account:view')">
  账户管理
</el-button>

<!-- 仅 super_admin 可见 -->
<el-button v-if="hasPermission('system_config:edit')">
  修改 Agent 配置
</el-button>

<!-- admin 及以上可见 -->
<el-button v-if="hasPermission('template:create')">
  创建模板
</el-button>
```

---

## 六、数据库迁移

### 6.1 迁移脚本

需要更新 `init_rbac_data.py`：

1. 删除旧的 `admin` 角色权限配置
2. 添加 `super_admin` 角色和权限
3. 调整权限分配矩阵

### 6.2 现有数据处理

```python
# 检查并更新现有角色
async def migrate_roles():
    async with async_session() as db:
        # 1. 创建 super_admin 角色
        # 2. 更新 admin 角色权限
        # 3. 不影响已有用户
        pass
```

---

## 七、测试验证

### 7.1 测试用例

| 测试场景 | 预期结果 |
|---------|---------|
| zch 登录 | 看到全部菜单（包含账户管理、系统配置） |
| super_admin 用户登录 | 看到全部菜单（包含账户管理、系统配置） |
| admin 用户登录 | 看不到账户管理、系统配置 |
| reviewer 用户登录 | 只看到学生管理、审核管理 |
| user 注册登录 | 只看到加分申请 |
| zch 操作账户 | 允许 |
| admin 操作账户 | 拒绝（无权限） |

### 7.2 验证步骤

```bash
# 1. 初始化数据
python -m src.scripts.init_rbac_data

# 2. 测试 zch
curl -X POST /api/authserver/admin/login \
  -d '{"username":"zch","password":"xxx"}'

# 3. 获取权限
curl /api/system/user/my/permissions \
  -H "Authorization: Bearer <token>"
# 期望: ["*"]

# 4. 测试普通 super_admin
# 需要手动创建用户并分配 super_admin 角色

# 5. 测试 admin
# 需要手动创建用户并分配 admin 角色
```

---

## 八、文档更新

### 8.1 需要更新的文档

| 文档 | 更新内容 |
|------|---------|
| `docs/rbac/README.md` | 更新角色说明 |
| `docs/rbac/implementation-plan.md` | 更新权限矩阵 |
| 用户手册 | 添加权限说明章节 |

### 8.2 用户权限说明

```
尊敬的用户：

您的账户权限说明：

• 超级管理员 (super_admin)
  可管理所有账户、修改系统配置、管理模板、审核申请等全部功能

• 管理员 (admin)
  可管理模板、查看和编辑学生信息、审核申请，但不能管理账户

• 审核员 (reviewer)
  可查看学生信息、审核学生提交的申请

• 学生 (user)
  可提交保研加分申请、查看自己的申请状态
```

---

## 九、附录

### 9.1 完整权限代码清单

| 权限代码 | 说明 | super_admin | admin | reviewer | user |
|----------|------|:-----------:|:-----:|:--------:|:----:|
| `account:view` | 账户列表 | ✅ | ❌ | ❌ | ❌ |
| `account:create` | 创建账户 | ✅ | ❌ | ❌ | ❌ |
| `account:edit` | 编辑账户 | ✅ | ❌ | ❌ | ❌ |
| `account:delete` | 删除账户 | ✅ | ❌ | ❌ | ❌ |
| `account:assign_role` | 分配角色 | ✅ | ❌ | ❌ | ❌ |
| `system_config:view` | 查看配置 | ✅ | ❌ | ❌ | ❌ |
| `system_config:agent` | Agent配置 | ✅ | ❌ | ❌ | ❌ |
| `system_config:smtp` | 邮件配置 | ✅ | ❌ | ❌ | ❌ |
| `system_config:edit` | 编辑配置 | ✅ | ❌ | ❌ | ❌ |
| `template:view` | 查看模板 | ✅ | ✅ | ❌ | ❌ |
| `template:create` | 创建模板 | ✅ | ✅ | ❌ | ❌ |
| `template:edit` | 编辑模板 | ✅ | ✅ | ❌ | ❌ |
| `template:delete` | 删除模板 | ✅ | ✅ | ❌ | ❌ |
| `student:view` | 查看学生 | ✅ | ✅ | ✅ | ❌ |
| `student:edit` | 编辑学生 | ✅ | ✅ | ❌ | ❌ |
| `review:pending` | 待审核 | ✅ | ✅ | ✅ | ❌ |
| `review:approved` | 已通过 | ✅ | ✅ | ✅ | ❌ |
| `review:approve` | 通过审核 | ✅ | ✅ | ✅ | ❌ |
| `review:reject` | 拒绝审核 | ✅ | ✅ | ✅ | ❌ |
| `apply:create` | 提交申请 | ✅ | ✅ | ❌ | ✅ |
| `apply:my` | 我的申请 | ✅ | ✅ | ❌ | ✅ |
| `apply:view` | 查看详情 | ✅ | ✅ | ✅ | ✅ |

### 9.2 相关文件清单

| 文件路径 | 说明 |
|----------|------|
| `src/models/user.py` | Permission 模型（需扩展字段） |
| `src/services/rbac_service.py` | 权限服务（已实现） |
| `src/services/auth_service.py` | 认证服务（注册自动分配 user 角色） |
| `src/app/routes/menu.py` | 菜单 API（已实现） |
| `src/scripts/init_rbac_data.py` | 初始化脚本（需更新） |
| `src/app/routes/system_config.py` | 系统配置 API（需新建） |
| `idfrontend-admin/src/stores/permission.ts` | 权限状态（已实现） |
| `idfrontend-admin/src/router/index.ts` | 路由守卫（已改造） |
