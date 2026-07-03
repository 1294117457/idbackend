# RBAC 实现问题分析

> 状态：基于 `src/` 目录代码全面审查，标注每个问题的严重程度和修复方向。
> 已按文档「用户信息获取dbmq.md」完成第一阶段改造（ContextVar + 每次查 DB），以下为改造后仍存在的问题。

---

## 问题总览

| # | 严重程度 | 影响范围 | 问题描述 |
|---|---|---|---|
| P1 | 🔴 高 | 全链路 | 中间件执行顺序错误：PermissionMiddleware 在外层，导致 AuthMiddleware 未执行时 ContextVar 无数据 |
| P2 | 🔴 高 | 所有路由 | 路由层重复查 DB：`RbacService.get_user_roles` / `get_user_permissions` 仍带 Redis 缓存，绕过 ContextVar |
| P3 | 🔴 高 | 所有路由 | `get_user_menu_tree` 返回所有权限，未按用户过滤 |
| P4 | 🟠 中 | 管理端 | 管理端路由缺少鉴权：任何登录用户都能访问用户/角色/权限管理接口 |
| P5 | 🟠 中 | 鉴权链路 | 未校验用户账号状态（banned / inactive），禁用用户仍可请求 |
| P6 | 🟠 中 | rbac_service | `assign_roles_to_user` 先清缓存再 commit，存在竞态窗口 |
| P7 | 🟡 低 | rbac_service | 缓存 key 不一致：PermissionMiddleware 用 `rbac:api:perm:`，RbacService 用 `rbac:api:`，缓存互相不命中 |
| P8 | 🟡 低 | deps.py | JWT 回退解析用 `or` 默认值，`payload.get("userId") or payload.get("user_id")` 两个 key 均缺失时 user_id=0 |

---

## 详细分析

### P1：中间件执行顺序错误（已修复，待确认）

**位置：** `src/main.py` 第 95-96 行

**问题：** Starlette/FastAPI 中 `add_middleware` 是栈式注册，后添加的先执行。当前代码：

```python
app.add_middleware(PermissionMiddleware)  # 先添加 → 外层 → 先执行
app.add_middleware(AuthMiddleware)        # 后添加 → 内层 → 后执行
```

执行顺序变成了：

```
1. PermissionMiddleware.dispatch() 先执行
   → 调用 get_user_id() 从 ContextVar 取值
   → 此时 AuthMiddleware 尚未执行，ContextVar 为空
   → user_id is None → 直接返回 401（错误位置）
2. AuthMiddleware.dispatch() 后执行
   → verify_token() 解析 JWT
   → set_current_user() 写入 ContextVar（永远不会被读到）
```

**修复（已执行）：** 调换顺序，使 AuthMiddleware 在外层先执行：

```python
app.add_middleware(PermissionMiddleware)  # 内层，后执行
app.add_middleware(AuthMiddleware)        # 外层，先执行
```

**正确顺序：**
```
1. AuthMiddleware → 解析 JWT，写入 {user_id, username} 到 ContextVar
2. PermissionMiddleware → 读 ContextVar，查 DB，写入完整信息到 ContextVar
3. 路由处理函数 → 读 ContextVar
```

---

### P2：路由层重复查 DB（RbacService 带 Redis 缓存，绕过 ContextVar）

**位置：** 多处路由文件

**问题：** `PermissionMiddleware` 已将用户完整信息写入 ContextVar，但路由层仍通过 `Depends(get_current_user)` 拿到的 `CurrentUser` 字段为空（ContextVar 解析失败时走 JWT 兜底，JWT 不含 roles/permissions），然后手动调 `RbacService.get_user_roles()` / `RbacService.get_user_permissions()` 重复查 DB 并走 Redis 缓存。

**受影响路由：**

```35:50:src/app/routes/menu.py
@router.get("/api/system/user/my/permissions")
async def get_my_permissions(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的所有权限列表

    用于前端按钮级权限控制
    """
    try:
        # 权限由 PermissionMiddleware 通过 Redis 实时获取；
        # 路由层直接调 service 拿真实权限，避免依赖 ContextVar 中已废弃字段。
        permissions = await RbacService.get_user_permissions(db, current_user.user_id)
        return success_response(permissions)
    except Exception as e:
        return error_response(str(e))
```

```54:80:src/app/routes/menu.py
@router.get("/api/system/user/me")
async def get_current_user_info(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ...
    roles = await RbacService.get_user_roles(db, current_user.user_id)
    permissions = await RbacService.get_user_permissions(db, current_user.user_id)
```

```220:227:src/app/routes/user.py
@router.get("/me/roles")
async def get_my_roles(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    roles = await RbacService.get_user_roles(db, user.user_id)
    return success_response({"roles": roles})
```

```53:72:src/app/routes/user.py
@router.get("/profile")
async def get_profile(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ...
    roles = await RbacService.get_user_roles(db, user.user_id)
```

```264:298:src/app/routes/user.py
@router.get("/admin/list")
async def list_users(...):
    ...
    for u in users:
        roles = await RbacService.get_user_roles(db, u.id)  # N+1 查询
```

**根本原因：** `deps.py` 的 `get_current_user()` 回退到 JWT 解析时 `roles=[] permissions=[]`，业务代码被迫调 `RbacService` 补查。`RbacService` 本身还带 Redis 缓存，导致同一请求内绕过了 ContextVar。

**修复方向：**

1. 路由层不再调 `RbacService.get_user_roles` / `get_user_permissions`，直接用 `CurrentUser.roles` / `CurrentUser.permissions`（已由 PermissionMiddleware 写入 ContextVar）
2. `RbacService.get_user_roles` / `get_user_permissions` 移除 Redis 缓存逻辑（与 PermissionMiddleware 保持一致）
3. `RbacService.get_user_roles` 返回值格式应改为 `List[Dict]`（含 role_id / role_name），与 ContextVar 格式对齐

---

### P3：`get_user_menu_tree` 返回所有权限，未按用户过滤

**位置：** `src/services/rbac_service.py` 第 658-678 行

**问题：** 函数文档声称"获取用户可访问的权限列表"，实际返回所有 `status=True` 的权限，完全没有按当前用户过滤。管理端用户和非管理端用户看到的是同一份菜单。

```658:678:src/services/rbac_service.py
@staticmethod
async def get_user_menu_tree(db: AsyncSession, user_id: int) -> List[dict]:
    """获取用户可访问的权限列表（按 sort_order 排序）"""
    from src.models.user import Permission

    result = await db.execute(
        select(Permission)
        .where(Permission.status == True)
        .order_by(Permission.sort_order)
    )
    permissions = result.scalars().all()
    # ↑ 无用户过滤，返回所有权限

    return [
        {
            "id": p.id,
            "permissionCode": p.permission_code,
            "permissionName": p.permission_name,
            "routePath": p.api_path,
            "sortOrder": p.sort_order,
        }
        for p in permissions
    ]
```

**修复方向：** JOIN 查询，按用户角色过滤权限（复用 PermissionMiddleware 的查询逻辑）。

---

### P4：管理端路由缺少鉴权

**位置：** `src/app/routes/user.py`、`src/app/routes/role.py`、`src/app/routes/permission.py`

**问题：** 所有管理端接口（创建/删除用户、分配角色/权限、删除角色等）仅要求 `Depends(get_current_user)` 验证登录，但**没有任何接口级权限码**绑定在 `permission` 表的 `api_path` 上，因此 `PermissionMiddleware` 对这些路由全部放行。

**当前无权限码绑定的管理接口：**

| 路由 | 接口 |
|---|---|
| `user.py` | `POST /api/user/admin/create`（创建用户） |
| `user.py` | `DELETE /api/user/admin/{user_id}`（删除用户） |
| `user.py` | `PUT /api/user/admin/{user_id}/status`（改用户状态） |
| `user.py` | `POST /api/user/{user_id}/roles`（分配用户角色） |
| `role.py` | `POST /api/system/role/create`（创建角色） |
| `role.py` | `PUT /api/system/role/update`（更新角色） |
| `role.py` | `DELETE /api/system/role/{role_id}`（删除角色） |
| `role.py` | `POST /api/system/role/assignPermissions`（分配权限给角色） |
| `permission.py` | `POST /api/system/permission/create`（创建权限） |
| `permission.py` | `PUT /api/system/permission/update`（更新权限） |
| `permission.py` | `DELETE /api/system/permission/{permission_id}`（删除权限） |

**修复方向（二选一）：**

**方案 A（推荐）：** 在 `permission` 表中为上述每个管理接口插入 `permission_code` 记录（如 `system:user:create`），并分配给 `admin` 角色。`PermissionMiddleware` 通过 `api_path` 匹配 `permission_code`，自动拦截无权限用户。

**方案 B：** 在 `role.py` / `user.py` 管理路由上手动添加 `Depends(require_permission("xxx"))`，但这需要先实现 `require_permission` 依赖函数，且不如方案 A 符合"path → permission" 的统一设计。

---

### P5：未校验用户账号状态

**位置：** `src/app/middleware/auth_middleware.py`、`src/app/middleware/permission_middleware.py`

**问题：** 当前仅检查 JWT token 有效性，未从 DB 查询用户状态。禁用用户（`status = banned` / `inactive`）的 token 仍然有效，可正常访问所有接口。

**修复方向：** 在 `PermissionMiddleware.load_user_full_info()` 中补充用户状态检查：

```python
user = await db.get(User, user_id)
if not user:
    return {...}  # user_id 无效
if user.status != UserStatus.ACTIVE.value:
    return JSONResponse({"code": 403, "msg": "账号已被禁用"}, status_code=403)
```

注意：这需要引入 `UserStatus` 枚举，且是单次额外 DB 查询（`db.get(User, user_id)` 已在 JOIN 查询前执行，可复用）。

---

### P6：`assign_roles_to_user` 缓存竞态窗口

**位置：** `src/services/rbac_service.py` 第 619-653 行

**问题：** 清缓存 → 删 DB 数据 → 插入新数据 → commit。顺序错误，应为：删数据 → 插数据 → commit → 清缓存。

当前代码在 `await db.commit()` 之前清缓存，若 `clear_user_cache` 失败（Redis 不可用），DB 已 commit 但缓存未清，导致新请求读到旧缓存。

```636:653:src/services/rbac_service.py
# 清除用户缓存
await RbacService.clear_user_cache(user_id)   # ← 应移到最后

# 删除旧角色
await db.execute(delete(UserRole).where(UserRole.user_id == user_id))

# 插入新角色
for role_id in role_ids:
    ...

await db.commit()                               # ← 应在清缓存之前
return True
```

同样问题存在于 `assign_permissions_to_role`（第 563-598 行）：清缓存也在 commit 之前。

---

### P7：缓存 key 前缀不一致

**位置：** `src/services/rbac_service.py` 和 `src/app/middleware/permission_middleware.py`

**问题：** `RbacService.API_PERM_KEY_PREFIX = "rbac:api:"`，而 `PermissionMiddleware` 用 `f"rbac:api:perm:{path}"`。两边写入不同 key，互相不命中。

```22:26:src/app/middleware/permission_middleware.py
_API_KEY_PREFIX = RbacService.API_PERM_KEY_PREFIX   # "rbac:api:"
_USER_KEY_PREFIX = RbacService.USER_PERMS_KEY       # "rbac:user:perms:"
```

**修复方向（第一阶段后）：** 两个模块均不再使用 Redis 缓存缓存用户权限，此问题在引入 MQ 阶段前可忽略（但第二阶段引入 L2 Redis 缓存时需统一 key 规范）。

---

### P8：JWT 回退解析 user_id 默认值

**位置：** `src/app/deps.py`

**问题：** `payload.get("userId") or payload.get("user_id", 0)` 中两个 key 均缺失时，`user_id` 被设为 `0`，后续路由会错误地以 `user_id=0` 查数据库。

```60:65:src/app/deps.py
return CurrentUser(
    user_id=payload.get("userId") or payload.get("user_id", 0),
    username=payload.get("username", ""),
    ...
)
```

**修复方向：** 两个 key 均缺失时应抛出 `HTTPException(401)`，而非静默给默认值：

```python
user_id = payload.get("userId") or payload.get("user_id")
if not user_id:
    raise HTTPException(status_code=401, detail="Token无效")
```

---

## 修复优先级建议

| 优先级 | 问题 | 理由 |
|---|---|---|
| P0（立即修复） | P1 中间件顺序 | 若未生效，所有请求均 401 |
| P1 | P4 管理端无鉴权 | 任何登录用户都可操作用户/角色/权限 |
| P1 | P2 路由层重复查 DB | 与第一阶段目标相悖，Redis 缓存仍带来不一致窗口 |
| P2 | P3 菜单不过滤 | 前端看到所有菜单项而非仅有所权限 |
| P2 | P5 用户状态未校验 | 禁用用户仍可操作 |
| P3 | P6 缓存竞态 | 仅 Redis 不可用时触发 |
| P4 | P7/P8 | 边缘场景 |

---

## 参考文件

- 中间件：`src/app/middleware/auth_middleware.py`、`src/app/middleware/permission_middleware.py`
- 上下文：`src/app/context.py`
- 依赖注入：`src/app/deps.py`
- 入口：`src/main.py`
- RBAC 服务：`src/services/rbac_service.py`
- 路由：`src/app/routes/user.py`、`src/app/routes/role.py`、`src/app/routes/permission.py`、`src/app/routes/menu.py`
- 模型：`src/models/user.py`
