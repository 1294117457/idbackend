# RBAC 权限系统 - 实施方案（简化版）

> 基于标准 RBAC 模型：User → Role → Permission
> 无需 interface_permissions 表，权限直接在接口声明

---

## 一、现状分析

### 1.1 已有组件

| 组件 | 位置 | 状态 | 说明 |
|------|------|------|------|
| **用户模型** | `src/models/user.py` | ✅ 完善 | User, Role, Permission, UserRole, RolePermission |
| **RBAC 服务** | `src/services/rbac_service.py` | ✅ 完善 | 包含白名单、缓存、CRUD |
| **依赖注入** | `src/app/deps.py` | ✅ 完善 | CurrentUser, require_role, require_permission |
| **JWT 工具** | `src/infra/jwt.py` | ⚠️ 需改造 | 需增加 roles, permissions 字段 |
| **白名单配置** | `src/infra/config.py` | ✅ 完善 | SYSTEM_ACCOUNTS |
| **权限管理 API** | `src/app/routes/permission.py` | ⚠️ 需改造 | 需增加自动扫描接口功能 |

### 1.2 待实现组件

| 组件 | 说明 | 优先级 |
|------|------|--------|
| **ContextVar** | 用户上下文存储（异步安全） | 🔴 必须 |
| **AuthMiddleware** | 解析 JWT，设置上下文，放行白名单 | 🔴 必须 |
| **PermissionMiddleware** | 基于 ContextVar 校验接口权限 | 🔴 必须 |

---

## 二、架构设计

### 2.1 权限模型

```
┌─────────┐     ┌───────────┐     ┌───────────────┐
│   User  │────▶│  UserRole │◀────│     Role      │
└─────────┘     └───────────┘     └───────┬───────┘
                                          │
                                          ▼
                                  ┌───────────────┐
                                  │RolePermission │
                                  └───────┬───────┘
                                          │
                                          ▼
                                  ┌───────────────┐
                                  │  Permission   │
                                  └───────────────┘

Permission.permission_code 格式: resource:action
  - user:create   → 创建用户
  - user:read     → 查看用户
  - user:update   → 更新用户
  - user:delete   → 删除用户
```

### 2.2 请求流程

```
┌─────────────────────────────────────────────────────────────────┐
│                        请求流程                                    │
│                                                                  │
│   请求 ──▶ AuthMiddleware ──▶ PermissionMiddleware ──▶ 业务代码   │
│               │                    │                              │
│               ▼                    ▼                              │
│        1. 解析 JWT           1. 查 ContextVar                   │
│        2. 白名单放行         2. 获取接口所需权限                   │
│        3. 设置 ContextVar    3. 比较用户权限                       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 三、详细实现

### Step 1: 创建 ContextVar 用户上下文

**文件**: `src/app/context.py`

```python
"""用户上下文 - 基于 ContextVar 的异步安全存储"""
from contextvars import ContextVar
from typing import Optional, Dict, Any, List


_current_user: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    'current_user',
    default=None
)


def set_current_user(user: Optional[Dict[str, Any]]) -> None:
    """设置当前用户到请求上下文"""
    _current_user.set(user)


def get_current_user() -> Optional[Dict[str, Any]]:
    """获取当前用户"""
    return _current_user.get()


def clear_current_user() -> None:
    """清除当前用户（请求结束时调用）"""
    _current_user.set(None)


def get_user_permissions() -> List[str]:
    """获取当前用户的权限列表"""
    user = get_current_user()
    if not user:
        return []
    return user.get("permissions", [])


def get_user_id() -> Optional[int]:
    """获取当前用户 ID"""
    user = get_current_user()
    return user.get("user_id") if user else None


def get_username() -> Optional[str]:
    """获取当前用户名"""
    user = get_current_user()
    return user.get("username") if user else None


def is_system_user() -> bool:
    """检查当前用户是否为 system_user（白名单）"""
    from src.services.rbac_service import RbacService
    username = get_username()
    if not username:
        return False
    return RbacService._is_admin(username)
```

---

### Step 2: 改造 JWT（增加 roles 和 permissions）

**修改**: `src/infra/jwt.py`

```python
def create_token(
    user_id: int,
    username: str,
    role: str,
    roles: List[str] = None,      # 新增：角色列表
    permissions: List[str] = None, # 新增：权限列表
    expires_hours: Optional[int] = None,
) -> str:
    """创建 access token"""
    from datetime import datetime, timedelta
    
    expire = datetime.utcnow() + timedelta(
        hours=expires_hours or settings.JWT_EXPIRE_HOURS
    )
    payload = {
        "userId": user_id,
        "username": username,
        "role": role,
        "roles": roles or [role],
        "permissions": permissions or [],
        "type": "access",
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(
    user_id: int,
    username: str,
    role: str,
    expires_days: Optional[int] = None,
) -> str:
    """创建 refresh token"""
    from datetime import datetime, timedelta
    import uuid
    
    jti = str(uuid.uuid4())
    expire = datetime.utcnow() + timedelta(
        days=expires_days or settings.JWT_REFRESH_EXPIRE_DAYS
    )
    payload = {
        "userId": user_id,
        "username": username,
        "role": role,
        "type": "refresh",
        "jti": jti,
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
```

---

### Step 3: 创建 AuthMiddleware

**文件**: `src/app/middleware/auth_middleware.py`

```python
"""认证中间件 - 解析 JWT，设置用户上下文"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.app.context import set_current_user, clear_current_user
from src.infra.jwt import verify_token, JWTError
from src.services.rbac_service import RbacService


class AuthMiddleware(BaseHTTPMiddleware):
    """请求认证中间件"""

    # 白名单路径（无需认证的接口）
    BYPASS_PATHS = [
        # 认证相关
        "/api/authserver/login",
        "/api/authserver/admin/login",
        "/api/authserver/register",
        "/api/authserver/captcha/generate",
        "/api/authserver/sendEmailCode",
        "/api/authserver/sendResetCode",
        "/api/authserver/reset-password",
        # 系统
        "/health",
        "/docs",
        "/openapi.json",
    ]

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 1. 检查白名单
        if self._is_bypass_path(path):
            return await call_next(request)

        # 2. 获取 Token
        auth_header = request.headers.get("Authorization", "")

        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"code": 401, "msg": "请先登录"}
            )

        token = auth_header[7:]

        # 3. 解析 JWT
        try:
            payload = verify_token(token)
        except JWTError as e:
            return JSONResponse(
                status_code=401,
                content={"code": 401, "msg": f"Token无效: {str(e)}"}
            )

        # 4. 构建用户对象
        user = {
            "user_id": payload.get("userId"),
            "username": payload.get("username"),
            "roles": payload.get("roles", [payload.get("role", "user")]),
            "permissions": payload.get("permissions", []),
        }

        # 5. system_user 自动授予全部权限
        if RbacService._is_admin(user["username"]):
            user["permissions"] = ["*"]
            user["roles"] = ["system"]

        # 6. 设置到 ContextVar
        set_current_user(user)

        try:
            return await call_next(request)
        finally:
            # 7. 请求结束清除上下文
            clear_current_user()

    def _is_bypass_path(self, path: str) -> bool:
        """检查路径是否在白名单中"""
        for bypass in self.BYPASS_PATHS:
            if path == bypass or path.startswith(bypass + "/"):
                return True
        return False
```

---

### Step 4: 创建 PermissionMiddleware

**文件**: `src/app/middleware/permission_middleware.py`

```python
"""权限校验中间件 - 基于 ContextVar 校验接口权限"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.app.context import get_current_user, get_user_permissions, is_system_user


class PermissionMiddleware(BaseHTTPMiddleware):
    """权限校验中间件"""

    # 无需权限校验的路径（与 AuthMiddleware 白名单分开）
    # AuthMiddleware 白名单是不需要认证的
    # 这里白名单是已认证但不需要特定权限的接口
    NO_PERMISSION_PATHS = [
        # 已认证用户获取自己信息的接口
        "/api/authserver/me",
        # 刷新 Token
        "/api/authserver/refresh",
    ]

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method.upper()

        # 1. 检查是否需要权限校验
        if self._no_permission_required(path):
            return await call_next(request)

        # 2. 获取当前用户
        user = get_current_user()

        if not user:
            return JSONResponse(
                status_code=401,
                content={"code": 401, "msg": "请先登录"}
            )

        # 3. system_user 直接通过
        if is_system_user():
            return await call_next(request)

        # 4. 从 ContextVar 获取接口需要的权限（由 Depends 装饰器设置）
        required_permission = getattr(request.state, "required_permission", None)

        # 5. 如果接口没有声明权限要求，直接通过
        if not required_permission:
            return await call_next(request)

        # 6. 检查用户权限
        user_permissions = get_user_permissions()

        if self._has_permission(user_permissions, required_permission):
            return await call_next(request)

        # 7. 无权限，拒绝
        return JSONResponse(
            status_code=403,
            content={"code": 403, "msg": f"权限不足，需要: {required_permission}"}
        )

    def _no_permission_required(self, path: str) -> bool:
        """检查是否不需要权限校验"""
        for bypass in self.NO_PERMISSION_PATHS:
            if path == bypass or path.startswith(bypass + "/"):
                return True
        return False

    def _has_permission(self, user_permissions: list, required: str) -> bool:
        """检查是否有权限"""
        if "*" in user_permissions:
            return True
        return required in user_permissions
```

---

### Step 5: 创建中间件目录

**文件**: `src/app/middleware/__init__.py`

```python
"""中间件模块"""
from .auth_middleware import AuthMiddleware
from .permission_middleware import PermissionMiddleware

__all__ = ["AuthMiddleware", "PermissionMiddleware"]
```

---

### Step 6: 注册中间件

**修改**: `src/main.py`

```python
from src.app.middleware.auth_middleware import AuthMiddleware
from src.app.middleware.permission_middleware import PermissionMiddleware

app = FastAPI(...)

# 注册中间件（后添加的先执行）
app.add_middleware(PermissionMiddleware)
app.add_middleware(AuthMiddleware)
```

---

### Step 7: 改造登录接口（返回完整权限到 JWT）

**修改**: `src/services/auth_service.py`

```python
@staticmethod
async def login(
    db: AsyncSession,
    username: str,
    password: str,
) -> tuple[User, str, str]:
    """登录，返回 (用户, access_token, refresh_token)"""
    # ... 保留原有验证逻辑 ...

    # 获取用户角色
    user_roles = await RbacService.get_user_roles(db, user.id)
    primary_role = user_roles[0] if user_roles else "user"

    # 检查是否为 system_user
    is_system = RbacService._is_admin(user.username)

    # 获取权限
    if is_system:
        permissions = ["*"]
        roles = ["system"]
    else:
        roles = user_roles
        permissions = await RbacService.get_user_permissions(db, user.id)

    # 生成 Token（包含完整权限信息）
    access_token = create_token(
        user_id=user.id,
        username=user.username,
        role=primary_role,
        roles=roles,          # 新增
        permissions=permissions,  # 新增
    )
    refresh_token = create_refresh_token(
        user_id=user.id,
        username=user.username,
        role=primary_role,
    )

    return user, access_token, refresh_token
```

同样修改 `admin_login` 方法。

---

### Step 8: 改造 Permission 创建（自动扫描接口）

**修改**: `src/app/routes/permission.py`

```python
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional, List
import re

from src.app.deps import get_db, require_admin
from src.app.response import success_response, error_response
from src.services.rbac_service import RbacService

router = APIRouter(prefix="/api/system/permission", tags=["权限管理"])


class ScanInterfacesRequest(BaseModel):
    """扫描接口请求"""
    prefix: Optional[str] = "/api"  # 接口前缀，如 /api 或 /api/system


class PermissionCreate(BaseModel):
    """创建权限请求"""
    permissionCode: str
    permissionName: str
    module: str
    description: Optional[str] = None
    sortOrder: int = 0


# ========== 接口扫描 ==========

@router.post("/scan-interfaces")
async def scan_interfaces(
    request: ScanInterfacesRequest,
    _: CurrentUser = Depends(require_admin),
):
    """扫描并生成权限代码建议

    从路由中提取 resource:action 格式的权限代码
    """
    from src.main import app

    permissions = []
    seen = set()

    def extract_permission(path: str, method: str) -> Optional[str]:
        """从路径提取权限代码"""
        # 示例: /api/system/user/create -> user:create
        # 示例: /api/users -> users (列表)

        # 移除前缀
        path = path.lstrip("/")
        parts = path.split("/")

        # 过滤掉路径参数如 {id}
        resource = None
        action = None

        for i, part in enumerate(parts):
            if part in ("system", "api"):
                continue
            if part.startswith("{") or part.isdigit():
                # 路径参数
                if i == len(parts) - 1:
                    action = "read" if method == "GET" else "delete"
                continue

            resource = part
            if i == len(parts) - 1:
                # 最后一个路径段作为 action
                action_map = {
                    "GET": "read",
                    "POST": "create",
                    "PUT": "update",
                    "PATCH": "update",
                    "DELETE": "delete",
                }
                action = action_map.get(method, "manage")

        if resource and action:
            return f"{resource}:{action}"
        return None

    # 遍历所有路由
    for route in app.routes:
        if hasattr(route, "path") and hasattr(route, "methods"):
            path = route.path

            # 过滤前缀
            if request.prefix and not path.startswith(request.prefix):
                continue

            for method in route.methods:
                if method in ("HEAD", "OPTIONS"):
                    continue

                perm_code = extract_permission(path, method)
                if perm_code and perm_code not in seen:
                    seen.add(perm_code)
                    permissions.append({
                        "path": path,
                        "method": method,
                        "suggestedCode": perm_code,
                        "module": path.split("/")[2] if len(path.split("/")) > 2 else "system",
                    })

    return success_response({
        "permissions": permissions,
        "count": len(permissions),
    })


@router.post("/create-batch")
async def create_permissions_batch(
    permissions: List[PermissionCreate],
    _: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """批量创建权限"""
    created = []
    failed = []

    for perm_data in permissions:
        try:
            await RbacService.create_permission(
                db=db,
                permission_code=perm_data.permissionCode,
                permission_name=perm_data.permissionName,
                module=perm_data.module,
                description=perm_data.description,
                sort_order=perm_data.sortOrder,
            )
            created.append(perm_data.permissionCode)
        except ValueError as e:
            failed.append({"code": perm_data.permissionCode, "error": str(e)})

    return success_response({
        "created": created,
        "createdCount": len(created),
        "failed": failed,
        "failedCount": len(failed),
    })
```

---

## 四、业务接口使用示例

### 方式 1: Depends 装饰器（推荐）

```python
# src/app/routes/user.py
from src.app.deps import require_permission, CurrentUser

@router.get("/users")
async def list_users(
    user: CurrentUser = Depends(require_permission("user:read"))
):
    """查询用户列表"""
    ...

@router.post("/users")
async def create_user(
    user: CurrentUser = Depends(require_permission("user:create"))
):
    """创建用户"""
    ...

@router.put("/users/{user_id}")
async def update_user(
    user_id: int,
    user: CurrentUser = Depends(require_permission("user:update"))
):
    """更新用户"""
    ...

@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    user: CurrentUser = Depends(require_permission("user:delete"))
):
    """删除用户"""
    ...
```

### 方式 2: 手动检查（特殊场景）

```python
from src.app.context import get_user_permissions, is_system_user

@router.post("/users/export")
async def export_users():
    """导出用户（权限检查在业务逻辑中）"""
    if not is_system_user():
        perms = get_user_permissions()
        if "user:read" not in perms:
            raise HTTPException(status_code=403, detail="权限不足")
    ...
```

---

## 五、权限命名规范

| 权限代码 | 对应接口 | 说明 |
|---------|---------|------|
| `user:create` | POST /api/users | 创建用户 |
| `user:read` | GET /api/users | 查看用户列表 |
| `user:update` | PUT /api/users/{id} | 更新用户 |
| `user:delete` | DELETE /api/users/{id} | 删除用户 |
| `role:create` | POST /api/system/role | 创建角色 |
| `role:read` | GET /api/system/role | 查看角色 |
| `role:update` | PUT /api/system/role | 更新角色 |
| `role:delete` | DELETE /api/system/role | 删除角色 |
| `role:assign` | PUT /api/system/role/{id}/permissions | 分配权限 |
| `permission:*` | 所有 /api/system/permission/* | 权限管理 |

---

## 六、文件清单

### 6.1 新增文件

| 文件路径 | 说明 |
|----------|------|
| `src/app/context.py` | ContextVar 用户上下文 |
| `src/app/middleware/__init__.py` | 中间件模块初始化 |
| `src/app/middleware/auth_middleware.py` | 认证中间件 |
| `src/app/middleware/permission_middleware.py` | 权限校验中间件 |

### 6.2 修改文件

| 文件路径 | 修改内容 |
|----------|----------|
| `src/infra/jwt.py` | JWT 增加 roles, permissions 字段 |
| `src/services/auth_service.py` | 登录时返回完整权限到 JWT |
| `src/main.py` | 注册中间件 |
| `src/app/routes/permission.py` | 增加接口扫描功能 |

---

## 七、执行顺序

```bash
# 1. 创建新文件
# - src/app/context.py
# - src/app/middleware/__init__.py
# - src/app/middleware/auth_middleware.py
# - src/app/middleware/permission_middleware.py

# 2. 修改现有文件
# - src/infra/jwt.py
# - src/services/auth_service.py
# - src/main.py
# - src/app/routes/permission.py

# 3. 重启服务
python -m src.main
```

---

## 八、版本记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2026-07-02 | 简化版实施方案，无需 interface_permissions 表 |
