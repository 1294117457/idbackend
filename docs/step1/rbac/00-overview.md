# RBAC 初始化方案 · 总览

> 本文只讲一件事：**怎么把 `role` / `permission` / `role_permission` 三张表的数据初始化好**。
> 不涉及 JWT、不涉及中间件、不涉及缓存——那些都已就绪。

---

## 1. 目标

跑一次 `init_rbac_data.py` 脚本后，DB 里应该长这样：

| 表 | 行数 | 来源 |
|----|------|------|
| `role` | 4 | 4 个系统角色（写死） |
| `permission` | ~70 | 覆盖所有受保护 API（写死） |
| `role_permission` | ~150 | 4 角色 × 各自权限码（写死） |
| `user_role` | 0 | 由管理端 / API 分配（**不初始化**） |

幂等：脚本可重复跑，已存在的数据**跳过**，缺的数据**补上**。

---

## 2. 4 个系统角色

| `role_code` | `role_name` | `is_system` | 谁能拥有 |
|------------|------------|------------|----------|
| `super_admin` | 超级管理员 | `True` | 由已存在的 super_admin 通过 `POST /api/user/{user_id}/roles` 分配 |
| `admin` | 管理员 | `True` | 业务运营、老师 |
| `reviewer` | 审核员 | `True` | 教秘 / 评委 |
| `user` | 学生 | `True` | 注册时自动获得 |

> ⚠️ 4 个角色**全部 `is_system=True`**，禁止通过 API 删除（`RbacService.delete_role` 会拒绝）。
>
> **super_admin 角色不需要绑定任何 permission_code**：`PermissionMiddleware` 识别到用户的角色列表里有 `roleCode="super_admin"` 时，直接给 `permissions=["*"]`，绕过逐项权限码校验。详见下方"两套超管机制"。

---

## 3. Permission 命名规范

### 3.1 格式

```
<资源>:<动作>
```

| 资源 | 含义 |
|------|------|
| `user` / `role` / `permission` | 账户管理类 |
| `application` | 加分申请 |
| `template` / `template_category` / `rule` | 模板与规则 |
| `score` | 成绩 |
| `extra_info` | 学生扩展字段 |
| `file` | 文件 |
| `system_config` | 系统配置 |
| `auth` | 认证 |

| 动作 | 含义 | 对应 HTTP |
|------|------|----------|
| `read` / `list` / `detail` | 查 | GET |
| `create` | 增 | POST |
| `update` | 改 | PUT / PATCH |
| `delete` | 删 | DELETE |
| `approve` / `reject` / `revoke` / `submit` / `cancel` | 业务动作 | POST |

### 3.2 字段约定

`permission` 表必填字段：

| 字段 | 含义 | 来源 |
|------|------|------|
| `permission_code` | 权限码，如 `template:create` | 唯一，写死 |
| `permission_name` | 显示名，如 "创建模板" | 写死 |
| `api_path` | 后端接口路径（用于反查） | 写死，**必须等于真实路由** |
| `group_code` / `group_name` | 分组 | 写死（前端菜单用） |
| `sort_order` | 排序 | 写死 |

---

## 4. 接口绑定原则

**原则：每个受保护 API 必须有一条 `permission` 记录**，中间件按 `api_path` 反查。

### 4.1 不需要绑定的接口（白名单 / 公共）

```
/api/authserver/login                  ← 公开
/api/authserver/admin/login            ← 公开
/api/authserver/register               ← 公开
/api/authserver/captcha/generate       ← 公开
/api/authserver/sendEmailCode          ← 公开
/api/authserver/sendResetCode          ← 公开
/api/authserver/reset-password         ← 公开
/api/authserver/me                     ← 已登录即可
/api/authserver/refresh                ← 已登录即可
/api/authserver/logout                 ← 已登录即可
/health
/docs
/openapi.json
```

### 4.2 需要绑定的接口（其余所有 `/api/*`）

**所有非公开、非"已登录即可"的接口都要绑权限码**。

详见 [`02-init-permissions.md`](./02-init-permissions.md)。

---

## 4.5 两套"超管"机制（完全独立，但效果一致）

`PermissionMiddleware` 有**两条独立的短路路径**，最终都返回 `permissions=["*"]`：

| 机制 | 触发条件 | 数据位置 | 走 DB 吗 | 用途 |
|------|---------|---------|---------|------|
| **`SYSTEM_ACCOUNTS` 白名单** | 用户名在 `.env` 的 `SYSTEM_ACCOUNTS` 里 | `.env` 文件 | ❌ 完全不走 DB | **逃生通道**——DB 清空 / RBAC 数据丢失时仍能登录 |
| **`super_admin` 角色** | 用户被绑定了 `super_admin` 角色（`role.role_code == "super_admin"`） | `role` + `user_role` 表 | ✅ 走 DB | **日常运营**——业务超管账号 |

**两者关系**：完全独立。代码上是两段并列的 `if` 分支：

```python
# src/app/middleware/permission_middleware.py

# 短路 1：账户白名单（先判断，不走 DB）
if is_system_account(username):
    set_user({..., "permissions": ["*"]})
    return await call_next(request)

# 加载用户（走 DB）
user_auth = await UserService.load_user_auth_info(user_id)
set_user(user_auth)

# 短路 2：super_admin 角色
if any(r.get("roleCode") == "super_admin" for r in user_auth.get("roles", [])):
    user_auth["permissions"] = ["*"]
    set_user(user_auth)
```

**为什么要并存**：
- 白名单是逃生通道——DB 全清空时还能登录，不依赖任何业务数据
- super_admin 角色是日常用的——通过管理端分配 / 回收，可被审计，可被管理端管理（管理端 `/api/system/role/list` 看到它）

**super_admin 角色绑定 0 条 permission_code**：
- 加新权限时，不用同步更新 super_admin 的绑定列表（省事）
- 真正生效靠的是中间件的角色短路，不是 DB 里的 role_permission

---

## 5. 4 角色权限分配原则

| 角色 | 原则 |
|------|------|
| `super_admin` | 所有权限 |
| `admin` | 业务管理（不含 RBAC 管理、不含系统配置） |
| `reviewer` | 只读 + 审核动作（无 revoke、无任何写权限） |
| `user` | 仅自己相关的接口（看自己的数据、提交自己的申请） |

---

## 6. 实施步骤

```bash
# 1. 编辑 init_rbac_data.py，按本文档写入 ROLES_DATA / PERMISSIONS_DATA / ROLE_PERMISSIONS
# 2. 跑脚本
cd /home/dustp/codes/idproject/idbackend
source .venv/bin/activate
python -m src.scripts.init_rbac_data

# 3. 验证 SQL
psql $DATABASE_URL -c "
SELECT r.role_code, COUNT(rp.permission_id) AS perm_count
FROM role r
LEFT JOIN role_permission rp ON rp.role_id = r.id
GROUP BY r.id, r.role_code
ORDER BY r.sort_order;
"
```

预期输出：
```
 super_admin | 0
 admin       | 51
 reviewer    | 16
 user        | 18
```

---

## 7. 后续维护（加了新接口怎么办）

1. 在 `PERMISSIONS_DATA` 加一行（`permission_code` / `api_path` / `group_*`）
2. 在 `ROLE_PERMISSIONS` 给需要的角色加上
3. 跑 `init_rbac_data.py`（幂等）

**原则**：任何新增的非公开 API 都必须同时配权限码，否则中间件默认放行（不安全）。

---

## 文档索引

| 文档 | 内容 |
|------|------|
| [`00-overview.md`](./00-overview.md) | 总览：目标 + 命名规范 + 接口绑定原则 |
| [`01-init-roles.md`](./01-init-roles.md) | 4 个 Role 的具体数据 + 字段说明 + 角色定位 |
| [`02-init-permissions.md`](./02-init-permissions.md) | 完整 Permission 清单 + 4 角色权限矩阵 + 设计取舍 |
| [`03-init-script.md`](./03-init-script.md) | **`init_rbac_data.py` 完整可执行版**（可直接复制覆盖原文件） |