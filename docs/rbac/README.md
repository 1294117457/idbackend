# RBAC 权限系统实现说明

> 更新日期：2026-07-03  
> 对应代码：`idpython`（FastAPI）

---

## 一、整体架构

```
HTTP 请求
   │
   ▼
AuthMiddleware          解析 JWT → 写入 {user_id, username} 到 ContextVar
   │                   无 token / token 无效 → 返回 401
   ▼
PermissionMiddleware    白名单超管 → 直接放行（["*"]）
   │                   普通用户：查 DB 获取状态/角色/权限
   │                   账号禁用 → 返回 401
   │                   路径无绑定权限 → 放行
   │                   权限不足 → 返回 403
   ▼
路由函数                通过 context.py 函数直接读取 ContextVar 中的用户信息
```

两个中间件职责完全分离：
- **AuthMiddleware**：只管"你是谁"（身份认证）
- **PermissionMiddleware**：只管"你能做什么"（授权）

---

## 二、数据模型

### 核心表关系

```
User ──M:N──► Role ──M:N──► Permission
       user_role      role_permission
```

### Permission 表核心字段

| 字段 | 说明 | 示例 |
|------|------|------|
| `permission_code` | 权限编码，格式 `module:action` | `template:read` |
| `permission_name` | 权限名称 | 查看模板 |
| `api_path` | 绑定的 API 路径 | `/api/bonus-template/list` |
| `status` | 是否启用 | `true` |

> `api_path` 是鉴权的核心：中间件通过路径查到所需 `permission_code`，再与用户权限集合比对。

### 角色表核心字段

| 字段 | 说明 | 示例 |
|------|------|------|
| `role_code` | 角色编码 | `admin`、`reviewer` |
| `role_name` | 角色名称 | 管理员 |
| `is_system` | 是否系统内置（不可删） | `true` |

---

## 三、请求鉴权流程

### 3.1 中间件执行顺序

`main.py` 中注册顺序决定执行顺序（后加的先执行）：

```python
app.add_middleware(PermissionMiddleware)  # 内层，后执行
app.add_middleware(AuthMiddleware)        # 外层，先执行
```

### 3.2 路径分类

| 类型 | 例子 | 处理方式 |
|------|------|---------|
| **完全公开路径** | `/api/authserver/login`、`/health` | 两个中间件都放行 |
| **已登录即可** | `/api/authserver/refresh`、`/api/authserver/logout` | AuthMiddleware 验 token，PermissionMiddleware 早返回 |
| **需要权限码** | `/api/bonus-template/list` 等 | 全流程鉴权 |

### 3.3 鉴权判定逻辑

```python
# permission_middleware.py - dispatch 方法核心逻辑

# 1. 白名单超管：跳过 DB，直接给全部权限
if is_system_account(username):
    set_user({..., "permissions": ["*"]})
    return await call_next(request)

# 2. 从 DB 加载用户状态 + 角色 + 权限
user_auth = await UserService.load_user_auth_info(user_id)
if user_auth is None:          # 账号已禁用
    return JSONResponse(401)

# 3. 查路径所需权限码
required = await RbacService.get_path_permission(path)
if not required:               # 路径未配置权限，默认开放
    return await call_next(request)

# 4. 权限比对
if "*" in user_perms or required in user_perms:
    return await call_next(request)

return JSONResponse(403)
```

---

## 四、超管白名单

### 配置方式

`.env` 文件中配置（逗号分隔）：

```env
SYSTEM_ACCOUNTS=zch,admin
```

### 效果

- 白名单用户登录后，`PermissionMiddleware` 直接跳过 DB 查询，写入 `permissions: ["*"]`
- 对所有路径放行，无需在 DB 中配置权限绑定
- DB 中看不到任何"超管"字样，账号看起来和普通用户一样

### 使用函数

```python
from src.infra.config import is_system_account

if is_system_account(username):
    ...
```

全项目只有 `permission_middleware.py` 和 `auth_service.py` 两处使用。

---

## 五、用户信息存取（ContextVar）

### 写入（中间件）

```python
# auth_middleware.py - 写入身份信息
set_user({"user_id": ..., "username": ...})

# permission_middleware.py - 补充完整鉴权信息
set_user({
    "user_id": 1,
    "username": "zch",
    "is_admin": False,
    "roles": [{"roleCode": "admin", "roleName": "管理员"}],
    "permissions": ["template:read", "user:view"],
})
```

### 读取（路由函数）

```python
from src.app.context import get_user_id, get_username, get_user_roles, get_user_permissions

user_id = get_user_id()           # int | None
username = get_username()         # str | None
roles = get_user_roles()          # List[{roleCode, roleName}]
perms = get_user_permissions()    # List[str]
```

不需要通过 `Depends()` 注入，直接调用函数即可（类似 Java 的 ThreadLocal）。

---

## 六、权限 CRUD 与接口绑定

### 管理端接口

| 接口 | 方法 | 功能 |
|------|------|------|
| `/api/system/permission/list` | GET | 权限列表 |
| `/api/system/permission/create` | POST | 创建权限 |
| `/api/system/permission/update` | PUT | 更新权限（含 apiPath） |
| `/api/system/permission/{id}` | DELETE | 删除权限 |
| `/api/system/permission/interfaces` | GET | 扫描所有可绑定的后端路由 |
| `/api/system/role/list` | GET | 角色列表 |
| `/api/system/role/create` | POST | 创建角色 |
| `/api/system/role/assignPermissions` | POST | 为角色分配权限 |
| `/api/user/{userId}/roles` | POST | 为用户分配角色 |

### 绑定权限到 API 的流程

1. 在权限管理页点"新增权限"
2. 填写 `permissionCode`（如 `template:read`）和 `permissionName`
3. 点"从接口选"，调用 `/api/system/permission/interfaces` 获取所有后端路由
4. 选择对应路由（如 `GET /api/bonus-template/list`），自动填充 `apiPath`
5. 保存后，该路由访问时将校验 `template:read` 权限

### `/interfaces` 实现原理

```python
@router.get("/interfaces")
async def get_all_interfaces(request: Request):
    # 通过 request.app.routes 扫描所有注册路由
    # 过滤 /api 开头，排除 HEAD/OPTIONS
    # 从路径推导建议的 permission_code
```

> 使用 `request.app` 而不是 `from src.main import app`，避免循环导入。

---

## 七、路径权限查询

`RbacService.get_path_permission(path)` 支持两种匹配：

```python
# 1. 精确匹配：/api/bonus-template/list → template:read
# 2. 前缀匹配：/api/system/role/5 → 匹配 /api/system/role/{id} → role:read
```

**注意**：未配置 `api_path` 的路由，中间件默认放行（不拦截）。需要鉴权的路由必须在权限管理中显式绑定。

---

## 八、核心文件索引

| 文件 | 职责 |
|------|------|
| `src/app/middleware/auth_middleware.py` | JWT 解析，身份认证 |
| `src/app/middleware/permission_middleware.py` | 鉴权流程编排 |
| `src/app/context.py` | ContextVar 存取用户信息 |
| `src/infra/config.py` | `is_system_account()` 白名单判断 |
| `src/services/user_service.py` | `load_user_auth_info()` 加载用户状态+角色+权限 |
| `src/services/rbac_service.py` | `get_path_permission()` 路径权限查询；角色/权限 CRUD |
| `src/app/routes/permission.py` | 权限管理 API + 接口扫描 |
| `src/app/routes/role.py` | 角色管理 API |
| `src/app/routes/user.py` | 用户角色分配 API |
| `src/models/user.py` | User、Role、Permission、UserRole、RolePermission 模型 |

---

## 九、前端对接要点

| 点 | 说明 |
|---|------|
| 403 → 弹 warning | 权限不足，保持登录状态（`http.ts` 已处理） |
| 401 → 自动登出 | Token 过期或账号禁用，触发 refresh → 失败 → 跳 `/login` |
| `GET /api/user/me/roles` | 返回 `[{roleCode, roleName}]` 数组，`profile.ts` 取 `r.roleCode` |
| `GET /api/user/{id}/roles` | 返回角色 ID 整数数组 `[1, 2, ...]`，用于 checkbox 预选 |
| 权限列表含 `module` 字段 | 由后端从 `permissionCode.split(':')[0]` 推导，无需单独存储 |
