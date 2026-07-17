# 4 个系统 Role 的初始化数据

> 本文档给出 `role` 表的 4 行 seed 数据。直接抄进 `init_rbac_data.py` 的 `ROLES_DATA`。

---

## 1. ROLES_DATA（4 行）

写到 `init_rbac_data.py`：

```python
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
```

---

## 2. 字段说明

| 字段 | 取值 | 说明 |
|------|------|------|
| `role_code` | 英文 snake_case | 唯一，写代码时引用 |
| `role_name` | 中文 | 显示用 |
| `description` | 中文 | 角色说明 |
| `sort_order` | `1` / `2` / `3` / `4` | 展示顺序 |
| `is_system` | 全 `True` | 4 个都是系统角色，不可被 API 删除 |

---

## 3. 角色定位对比

| 维度 | super_admin | admin | reviewer | user |
|------|------------|-------|----------|------|
| 能否进入管理后台（`/api/authserver/admin/login`） | ✅ | ✅ | ✅ | ❌ |
| 能否管理用户（增删改） | ✅ | ✅（部分）| ❌ | ❌ |
| 能否管 RBAC（角色/权限） | ✅ | ❌ | ❌ | ❌ |
| 能否改系统配置（Agent/SMTP） | ✅ | ❌ | ❌ | ❌ |
| 能否审核申请 | ✅ | ✅ | ✅ | ❌ |
| 能否撤回已通过申请 | ✅ | ✅ | ❌ | ❌ |
| 能否管理模板/规则 | ✅ | ✅ | ❌ | ❌ |
| 能否提交申请 | ✅ | ✅ | ❌ | ✅ |
| 默认获得方式 | super_admin 分配 | super_admin 分配 | super_admin 分配 | 注册时自动获得 |

---

## 4. 用户怎么获得这些角色

| 角色 | 获得方式 |
|------|---------|
| `super_admin` | 由已存在的 super_admin 通过 `POST /api/user/{user_id}/roles` 分配（DB 清空等紧急情况用 `.env` 的 `SYSTEM_ACCOUNTS` 白名单兜底登录） |
| `admin` | super_admin 通过 `POST /api/user/{user_id}/roles` 分配 |
| `reviewer` | super_admin 或 admin 分配 |
| `user` | 学生通过 `/api/authserver/register` 自动绑定（service 层逻辑） |

> ⚠️ `init_rbac_data.py` **不初始化 user_role**——user_role 表为空，由上面这些入口在运行时填充。

---

## 5. 校验 SQL（跑完脚本后执行）

```sql
-- 1. 4 角色是否就位
SELECT id, role_code, role_name, is_system, sort_order
FROM role
ORDER BY sort_order;

-- 预期：
--  1 | super_admin | 超级管理员 | t | 1
--  2 | admin       | 管理员    | t | 2
--  3 | reviewer    | 审核员    | t | 3
--  4 | user        | 学生      | t | 4

-- 2. 每个角色的权限数（应为：0 / 51 / 16 / 18）
SELECT r.role_code, COUNT(rp.permission_id) AS perm_count
FROM role r
LEFT JOIN role_permission rp ON rp.role_id = r.id
GROUP BY r.id, r.role_code
ORDER BY r.sort_order;

-- 3. user_role 应为空（除非手工调过 API）
SELECT COUNT(*) FROM user_role;
```
---

## 6. super_admin 角色 vs SYSTEM_ACCOUNTS 白名单

两者**完全独立**，但效果都是"全部权限"：

| 维度 | super_admin 角色 | SYSTEM_ACCOUNTS 白名单 |
|------|----------------|---------------------|
| 数据位置 | `role` + `user_role` 表（DB） | `.env` 文件 |
| 触发条件 | 用户被分配了 super_admin 角色 | 用户名在白名单里 |
| 是否走 DB 查询 | ✅ 走（查角色） | ❌ 完全不走 |
| 是否需要 super_admin 绑定 permission_code | ❌ 绑 0 条即可 | ❌ 无关系 |
| 中间件判定 | 加载 user_auth 后判断 roles 含 super_admin | 直接判断 username |
| 最终效果 | `permissions=["*"]` | `permissions=["*"]` |
| 用途 | 日常运营（业务超管账号） | 逃生通道（DB 损坏 / 清空时也能登） |
| 可被管理端管理 | ✅（通过 `/api/system/role/list` 看到） | ❌（改 .env 重启） |

**中间件实现位置**：`src/app/middleware/permission_middleware.py`，两段并列的 `if` 分支：

```python
# 1. 账户白名单（先判断，不走 DB）
if is_system_account(username):
    set_user({..., "permissions": ["*"]})
    return await call_next(request)

# 加载用户（走 DB）
user_auth = await UserService.load_user_auth_info(user_id)
set_user(user_auth)

# 2. super_admin 角色短路（新增）
if any(r.get("roleCode") == "super


---

## 6. super_admin 角色 vs SYSTEM_ACCOUNTS 白名单

两者**完全独立**，但效果都是"全部权限"：

| 维度 | super_admin 角色 | SYSTEM_ACCOUNTS 白名单 |
|------|----------------|---------------------|
| 数据位置 | `role` + `user_role` 表（DB） | `.env` 文件 |
| 触发条件 | 用户被分配了 super_admin 角色 | 用户名在白名单里 |
| 是否走 DB 查询 | ✅ 走（查角色） | ❌ 完全不走 |
| 是否需要 super_admin 绑定 permission_code | ❌ 绑 0 条即可 | ❌ 无关系 |
| 中间件判定 | 加载 user_auth 后判断 roles 含 super_admin | 直接判断 username |
| 最终效果 | `permissions=["*"]` | `permissions=["*"]` |
| 用途 | 日常运营（业务超管账号） | 逃生通道（DB 损坏 / 清空时也能登） |
| 可被管理端管理 | ✅（通过 `/api/system/role/list` 看到） | ❌（改 .env 重启） |

**中间件实现位置**：`src/app/middleware/permission_middleware.py`，两段并列的 `if` 分支：

```python
# 1. 账户白名单（先判断，不走 DB）
if is_system_admin(username):
    set_user({..., "permissions": ["*"]})
    return await call_next(request)

# 加载用户（走 DB）
user_auth = await UserService.load_user_auth_info(user_id)
set_user(user_auth)

# 2. super_admin 角色短路（新增）
if any(r.get("roleCode") == "super_admin" for r in user_auth.get("roles", [])):
    user_auth["permissions"] = ["*"]
    set_user(user_auth)
```

**为什么 super_admin 角色绑定 0 条 permission_code**：
- 加新权限时不用同步更新 super_admin 的绑定列表（避免漏配）
- 真正生效靠中间件的角色短路，不是 DB 里的 role_permission
- 管理端 `/api/system/role/{id}/permissions` 看到这个角色 0 条权限，前端根据 `is_system=true` 判断显示"超级管理员（拥有全部权限）"

**典型使用流程**：

```bash
# 1. .env 配置逃生通道
SYSTEM_ACCOUNTS=admin

# 2. 启动应用（lifespan 自动跑 init_rbac_data，幂等建 4 角色 + 89 个权限码）
uvicorn main:app

# 3. 用 admin 账号登录（走白名单短路）→ 在管理端创建另一个用户，给该用户分配 super_admin 角色
#    后续该用户登录就走"角色短路"，不再依赖白名单
```
