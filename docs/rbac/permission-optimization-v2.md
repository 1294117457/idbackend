# 权限优化方案 v2

> 本文档描述基于 RBAC 的权限系统优化方案，支持白名单用户绕过 RBAC 获取全部权限，并可通过动态配置实现接口权限自动校验。

---

## 核心设计总结

### 组件关系图

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                              用户请求流程                                          │
│                                                                                  │
│    ┌──────────┐      ┌─────────────────┐      ┌──────────────────────────┐      │
│    │  请求    │ ──── │ AuthMiddleware  │ ──── │ PermissionMiddleware     │      │
│    │          │      │   (Interceptor)  │      │                          │      │
│    └──────────┘      └────────┬────────┘      └──────────┬───────────────┘      │
│                               │                            │                       │
│                               ▼                            ▼                       │
│                    ┌─────────────────┐           ┌─────────────────┐             │
│                    │  1. 解析 JWT    │           │ 1. 查表获取接口  │             │
│                    │  2. 白名单放行   │           │    需要的权限    │             │
│                    │  3. ContextVar  │           │                 │             │
│                    │    设置用户     │           │ 2. 从 ContextVar│             │
│                    │                 │           │    获取用户权限  │             │
│                    └────────┬────────┘           │                 │             │
│                             │                    │ 3. 比较校验      │             │
│                             ▼                    └────────┬────────┘             │
│                    ┌─────────────────┐                     │                      │
│                    │ ContextVar     │◀────────────────────┘                      │
│                    │ 存储用户信息    │                                              │
│                    └─────────────────┘                                            │
│                                                                                  │
└────────────────────────────────────────────────────────────────────────────────┘
```

### 核心组件职责

| 组件 | 对应 Java 概念 | 职责 | 关键代码 |
|------|---------------|------|---------|
| **ContextVar** | ThreadLocal | 存储当前请求的用户信息 | `set_current_user(user)` / `get_current_user()` |
| **AuthMiddleware** | Interceptor + HandlerInterceptor | 前置处理：解析 JWT、放行白名单、设置上下文 | JWT 解析 → 白名单检查 → `set_current_user()` |
| **PermissionMiddleware** | 权限拦截器 | 校验权限：查表获取接口需要的权限 + ContextVar 获取用户权限 → 比较 | 查 `interface_permissions` 表 → `get_user_permissions()` → 比较 |
| **JWT** | Token | 用户身份凭证，携带用户信息 | `verify_token(token)` |
| **RBAC** | 权限模型 | 用户-角色-权限三层关系 | `get_user_roles()` / `get_user_permissions()` |

### 完整请求流程

```
1. 用户发起请求（带 JWT Token）
         │
         ▼
2. AuthMiddleware (前置拦截)
   ├── 检查路径是否在 bypass_paths 白名单中？
   │   ├── 是 → 直接放行（登录、注册、健康检查等）
   │   └── 否 → 继续
   │
   ├── 从 Header 提取 Authorization: Bearer <token>
   ├── JWT 解析 → 获取用户信息（user_id, username, roles, permissions）
   ├── 检查是否为 system_user？
   │   ├── 是 → permissions = ["*"]
   │   └── 否 → 保持原权限
   │
   └── ContextVar.set_current_user(user) → 设置用户上下文
         │
         ▼
3. PermissionMiddleware (权限校验)
   ├── 获取请求路径和方法
   ├── 查询 interface_permissions 表：此接口需要什么权限？
   ├── 接口未配置权限？ → 直接放行
   │
   ├── 获取当前用户权限：ContextVar.get_user_permissions()
   ├── 检查是否为 system_user？ → 直接放行
   │
   ├── 比较用户权限 vs 接口要求权限
   │   ├── 有权限 → 放行，进入业务代码
   │   └── 无权限 → 返回 403 Forbidden
         │
         ▼
4. 业务代码执行
   ├── 通过 ContextVar.get_current_user() 获取当前用户
   └── 执行业务逻辑
         │
         ▼
5. 请求结束
   └── ContextVar.clear_current_user() → 清除上下文
```

### 白名单/放行路径

| 路径 | 说明 | 处理方式 |
|------|------|---------|
| `/api/auth/login` | 登录接口 | bypass_paths 白名单放行，无需 Token |
| `/api/auth/register` | 注册接口 | bypass_paths 白名单放行，无需 Token |
| `/health` | 健康检查 | bypass_paths 白名单放行 |
| `/docs` | API 文档 | bypass_paths 白名单放行 |

### ContextVar 存储结构

```python
# 当前用户数据结构
{
    "user_id": 1,
    "username": "admin",
    "roles": ["admin"],
    "permissions": ["*"],  # system_user 或拥有全部权限
}
```

---

## 一、设计概述

### 1.1 核心目标

| 目标 | 说明 |
|------|------|
| **白名单机制** | `system_users` 绕过 RBAC，任何时候都拥有全部权限 |
| **RBAC 体系** | 普通用户的权限通过 Role-Permission 模型管理 |
| **动态接口配置** | 接口权限通过数据库配置，无需在代码中声明 |
| **前端权限** | 按钮、菜单、路由根据权限动态展示 |

### 1.2 用户类型

| 用户类型 | 权限来源 | 说明 |
|---------|---------|------|
| `system_users` | 白名单 | 绕过 RBAC，`permissions=["*"]` |
| 普通用户 | RBAC | 根据绑定的角色查询权限 |

### 1.3 方案选择

| 方案 | 适用场景 | 实现方式 |
|------|---------|---------|
| **动态中间件（推荐）** | 需要管理端动态配置接口权限 | 中间件自动校验，无需代码声明 |
| **手动 Depends** | 接口权限固定不变 | 代码中写 `Depends(require_permission(...))` |

---

## 二、权限模型

### 2.1 架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                           用户请求                                    │
│                                │                                     │
│                                ▼                                     │
│   ┌────────────────────────────────────────────────────────────────┐ │
│   │                      中间件链                                    │ │
│   │                                                              │ │
│   │   ┌───────────────┐    ┌─────────────────┐    ┌───────────┐ │ │
│   │   │ AuthMiddleware │ → │ PermissionMiddleware │ → │ 业务处理  │ │ │
│   │   │  JWT 认证     │    │   动态权限校验   │    │           │ │ │
│   │   │  设置上下文   │    │  查表+ContextVar │    │           │ │ │
│   │   └───────────────┘    └─────────────────┘    └───────────┘ │ │
│   │                                                              │ │
│   └────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘

                            RBAC 数据模型
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│   ┌───────────┐       ┌───────────┐       ┌─────────────────┐      │
│   │  User     │──────▶│  UserRole │◀──────│      Role       │      │
│   │   用户    │       │   用户角色  │       │      角色       │      │
│   └───────────┘       └───────────┘       └────────┬────────┘      │
│                                                     │                 │
│                                                     ▼                 │
│                                             ┌─────────────────┐      │
│                                             │ RolePermission  │      │
│                                             │   角色权限      │      │
│                                             └────────┬────────┘      │
│                                                      │                 │
│                                                      ▼                 │
│                                             ┌─────────────────┐      │
│                                             │   Permission    │      │
│                                             │     权限        │      │
│                                             └─────────────────┘      │
│                                                                     │
│   ┌───────────────────┐                                              │
│   │InterfacePermission│  ← 动态配置：接口需要什么权限                  │
│   │   接口权限绑定    │                                              │
│   └───────────────────┘                                              │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 数据库表结构

```sql
-- 用户表
CREATE TABLE users (
    id INT PRIMARY KEY AUTO_INCREMENT,
    username VARCHAR(50) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 角色表
CREATE TABLE roles (
    id INT PRIMARY KEY AUTO_INCREMENT,
    code VARCHAR(50) UNIQUE NOT NULL COMMENT '角色代码',
    name VARCHAR(100) NOT NULL COMMENT '角色名称',
    description VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 权限表
CREATE TABLE permissions (
    id INT PRIMARY KEY AUTO_INCREMENT,
    code VARCHAR(100) UNIQUE NOT NULL COMMENT '权限代码',
    name VARCHAR(100) NOT NULL COMMENT '权限名称',
    description VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 用户角色关联表
CREATE TABLE user_roles (
    user_id INT NOT NULL,
    role_id INT NOT NULL,
    PRIMARY KEY (user_id, role_id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (role_id) REFERENCES roles(id)
);

-- 角色权限关联表
CREATE TABLE role_permissions (
    role_id INT NOT NULL,
    permission_id INT NOT NULL,
    PRIMARY KEY (role_id, permission_id),
    FOREIGN KEY (role_id) REFERENCES roles(id),
    FOREIGN KEY (permission_id) REFERENCES permissions(id)
);

-- 【新增】接口权限绑定表（动态配置核心）
CREATE TABLE interface_permissions (
    id INT PRIMARY KEY AUTO_INCREMENT,
    path VARCHAR(255) NOT NULL COMMENT '接口路径，如 /api/users',
    method VARCHAR(10) NOT NULL COMMENT '请求方法，如 POST, GET',
    required_permission VARCHAR(100) COMMENT '需要的权限代码',
    description VARCHAR(255) COMMENT '接口描述',
    is_active BOOLEAN DEFAULT TRUE COMMENT '是否启用',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY (path, method)
);

-- 无需权限的接口白名单（登录、公开接口等）
CREATE TABLE bypass_paths (
    id INT PRIMARY KEY AUTO_INCREMENT,
    path_pattern VARCHAR(255) NOT NULL COMMENT '路径模式，支持 * 模糊匹配',
    method VARCHAR(10) DEFAULT '*' COMMENT '方法，* 表示所有',
    description VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 三、白名单机制

### 3.1 配置

```python
# src/infra/config.py
class Settings(BaseSettings):
    # 系统内置账户（白名单）
    SYSTEM_ACCOUNTS: List[str] = ["admin", "system"]
```

### 3.2 判断方法

```python
# src/services/rbac_service.py
class RbacService:
    
    @staticmethod
    def is_system_user(username: str) -> bool:
        """检查是否为系统用户（白名单）"""
        return username in settings.SYSTEM_ACCOUNTS
```

### 3.3 白名单作用

| 场景 | system_user 行为 |
|------|------------------|
| **任何时候** | 绕过 RBAC，`permissions=["*"]` |
| **登录** | 直接通过，无需特殊处理 |
| **接口访问** | 自动获得全部权限 |
| **权限管理** | 可以管理所有权限和角色 |

---

## 四、动态权限校验（推荐方案）

### 4.1 设计思路（类比 Java）

| Java 实现 | Python 实现 | 说明 |
|-----------|------------|------|
| `ThreadLocal` | `ContextVar` | 存储当前请求用户上下文（异步安全） |
| `Interceptor` | `Middleware` | 拦截请求，解析 Token，设置上下文 |
| `@RequiresPermissions` | 数据库配置 | 声明接口需要的权限 |
| 注解 + 反射 | 中间件 + 查表 | 自动校验权限 |

### 4.2 核心组件

```
请求 → AuthMiddleware → 从 JWT 解析用户 → ContextVar.set(user)
                         ↓
                   PermissionMiddleware → 从 interface_permissions 查需要的权限
                         ↓
                   ContextVar.get() 获取用户权限
                         ↓
                   比较：有权限放行 / 无权限 403
```

---

## 五、详细实现

### 5.1 ContextVar 用户上下文

```python
# src/app/context.py
"""
Python 3.7+ ContextVar - 异步安全的 ThreadLocal 替代
"""
from contextvars import ContextVar
from typing import Optional, Dict, Any

# 存储当前用户信息
_current_user: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    'current_user', 
    default=None
)


def set_current_user(user: Optional[Dict[str, Any]]) -> None:
    """设置当前用户到请求上下文"""
    _current_user.set(user)


def get_current_user() -> Optional[Dict[str, Any]]:
    """获取当前用户（从 ContextVar）"""
    return _current_user.get()


def clear_current_user() -> None:
    """清除当前用户（请求结束时调用）"""
    _current_user.set(None)


def get_user_permissions() -> list:
    """获取当前用户的权限列表"""
    user = get_current_user()
    if not user:
        return []
    return user.get("permissions", [])


def is_system_user() -> bool:
    """检查当前用户是否为 system_user"""
    from src.services.rbac_service import RbacService
    user = get_current_user()
    if not user:
        return False
    return RbacService.is_system_user(user.get("username", ""))
```

### 5.2 Auth 中间件 - JWT 解析并设置上下文

```python
# src/app/middleware/auth_middleware.py
"""
认证中间件：解析 Token，设置用户上下文到 ContextVar
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.app.context import set_current_user, clear_current_user
from src.services.rbac_service import RbacService


class AuthMiddleware(BaseHTTPMiddleware):
    """认证中间件 - 每个请求都会执行"""
    
    async def dispatch(self, request: Request, call_next):
        user = None
        
        try:
            # 1. 从 Header 获取 Token
            auth_header = request.headers.get("Authorization", "")
            
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
                
                # 2. 解析 Token（解码 JWT）
                payload = self._decode_token(token)
                
                if payload:
                    # 3. 构建用户对象
                    user = {
                        "user_id": payload.get("user_id"),
                        "user_id_int": payload.get("uid"),  # 根据实际 JWT payload 调整
                        "username": payload.get("sub") or payload.get("username"),
                        "roles": payload.get("roles", []),
                        "permissions": payload.get("permissions", []),
                    }
                    
                    # 4. system_user 自动授予全部权限
                    if RbacService.is_system_user(user["username"]):
                        user["permissions"] = ["*"]
                    
                    # 5. 设置到 ContextVar
                    set_current_user(user)
            
            # 6. 继续处理请求
            response = await call_next(request)
            return response
            
        except Exception as e:
            # JWT 解析失败，记录日志但不阻断请求
            # 请求会继续，但在 context 中无用户信息
            return await call_next(request)
            
        finally:
            # 7. 请求结束清除上下文（重要！防止内存泄漏）
            clear_current_user()
    
    def _decode_token(self, token: str) -> Optional[dict]:
        """解码 JWT Token"""
        from src.services.auth_service import AuthService
        try:
            return AuthService.decode_token(token)
        except Exception:
            return None
```

### 5.3 Permission 中间件 - 动态权限校验

```python
# src/app/middleware/permission_middleware.py
"""
权限校验中间件：从数据库查询接口需要的权限，自动校验
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from sqlalchemy import select

from src.app.context import get_current_user, is_system_user, get_user_permissions
from src.models.database import async_session
from src.models.rbac import InterfacePermission, BypassPath


class PermissionMiddleware(BaseHTTPMiddleware):
    """权限校验中间件 - 自动校验接口权限"""
    
    # 缓存已查询的接口权限（生产环境建议用 Redis）
    _permission_cache: dict = {}
    
    async def dispatch(self, request: Request, call_next):
        # 1. 获取请求路径和方法
        path = request.url.path
        method = request.method.upper()
        
        # 2. 检查是否在 bypass 列表（无需权限的接口）
        if await self._is_bypass_path(path, method):
            return await call_next(request)
        
        # 3. 查询接口需要的权限
        required_permission = await self._get_required_permission(path, method)
        
        # 4. 如果接口没有配置权限要求，直接通过
        if not required_permission:
            return await call_next(request)
        
        # 5. 获取当前用户
        user = get_current_user()
        
        # 6. 未登录用户拒绝
        if not user:
            return JSONResponse(
                status_code=401,
                content={"detail": "请先登录"}
            )
        
        # 7. system_user 直接通过
        if is_system_user():
            return await call_next(request)
        
        # 8. 检查用户权限
        user_permissions = get_user_permissions()
        
        if self._has_permission(user_permissions, required_permission):
            return await call_next(request)
        
        # 9. 无权限，拒绝
        return JSONResponse(
            status_code=403,
            content={"detail": f"权限不足，需要: {required_permission}"}
        )
    
    async def _is_bypass_path(self, path: str, method: str) -> bool:
        """检查是否在白名单路径中"""
        async with async_session() as db:
            result = await db.execute(
                select(BypassPath).where(
                    (BypassPath.path_pattern == path) |
                    (BypassPath.path_pattern == f"{path}/*") |
                    (BypassPath.path_pattern.like(path.rstrip('/') + '/*'))
                )
            )
            bypass = result.scalars().first()
            
            if bypass:
                # 检查方法是否匹配
                if bypass.method == '*' or bypass.method == method:
                    return True
        return False
    
    async def _get_required_permission(self, path: str, method: str) -> Optional[str]:
        """获取接口需要的权限"""
        cache_key = f"{method}:{path}"
        
        # 1. 先查缓存
        if cache_key in self._permission_cache:
            return self._permission_cache[cache_key]
        
        # 2. 查数据库
        async with async_session() as db:
            result = await db.execute(
                select(InterfacePermission).where(
                    InterfacePermission.path == path,
                    InterfacePermission.method == method,
                    InterfacePermission.is_active == True
                )
            )
            interface_perm = result.scalar_one_or_none()
        
        permission = interface_perm.required_permission if interface_perm else None
        
        # 3. 缓存结果
        self._permission_cache[cache_key] = permission
        
        return permission
    
    def _has_permission(self, user_permissions: list, required: str) -> bool:
        """检查是否有权限"""
        # 通配符 * 匹配所有
        if "*" in user_permissions:
            return True
        return required in user_permissions
```

### 5.4 注册中间件

```python
# src/main.py
from fastapi import FastAPI
from src.app.middleware.auth_middleware import AuthMiddleware
from src.app.middleware.permission_middleware import PermissionMiddleware

app = FastAPI()

# 注册中间件（顺序很重要！）
# 1. AuthMiddleware 先执行 - 设置用户上下文
# 2. PermissionMiddleware 后执行 - 校验权限
app.add_middleware(PermissionMiddleware)
app.add_middleware(AuthMiddleware)

# 注册路由...
```

### 5.5 业务接口 - 无需权限代码

```python
# src/app/routes/user.py
"""
使用动态权限校验后，业务接口无需写权限代码
权限由 interface_permissions 表配置
"""

@router.post("/users")
async def create_user(request: CreateUserRequest):
    """
    创建用户 - 权限由 PermissionMiddleware 自动校验
    无需写 Depends(require_permission("user:create"))
    """
    # 业务逻辑
    ...

@router.get("/users")
async def list_users():
    """
    查询用户 - 权限由 PermissionMiddleware 自动校验
    """
    ...

@router.delete("/users/{user_id}")
async def delete_user(user_id: int):
    """
    删除用户 - 权限由 PermissionMiddleware 自动校验
    """
    ...
```

---

## 六、管理端功能

### 6.1 功能列表

| 模块 | 功能 | 说明 |
|------|------|------|
| **Permission 管理** | 创建/修改/删除权限 | 维护权限代码和名称 |
| **Role 管理** | 创建/修改/删除角色 | 给角色绑定权限 |
| **User 管理** | 分配/移除角色 | 给用户分配角色 |
| **接口权限** | 绑定接口与角色 | 给接口分配需要的权限 |
| **Bypass 路径** | 配置无需权限的接口 | 登录、公开接口等 |

### 6.2 接口权限配置页面

```
┌─────────────────────────────────────────────────────────────────┐
│ 接口权限配置                                                       │
├─────────────────────────────────────────────────────────────────┤
│ 路径                     │ 方法  │ 所需权限      │ 操作           │
├─────────────────────────┼───────┼───────────────┼───────────────│
│ /api/auth/login          │ POST  │ (无需权限)    │ [编辑] [删除]  │
│ /api/auth/logout         │ POST  │ (无需权限)    │ [编辑] [删除]  │
│ /api/users               │ GET   │ user:read     │ [编辑]        │
│ /api/users               │ POST  │ user:create   │ [编辑]        │
│ /api/users/{id}          │ PUT   │ user:update   │ [编辑]        │
│ /api/users/{id}          │ DELETE│ user:delete   │ [编辑]        │
│ /api/roles               │ *     │ role:*        │ [编辑]        │
└─────────────────────────────────────────────────────────────────┘
```

### 6.3 管理端 API

```python
# src/app/routes/admin/interface_permission.py

@router.get("/admin/interfaces")
async def list_interfaces(
    path: str = None,
    method: str = None,
    page: int = 1,
    page_size: int = 20,
):
    """获取接口权限配置列表"""
    ...

@router.post("/admin/interfaces")
async def create_interface_permission(
    request: InterfacePermissionCreate,
):
    """创建接口权限配置"""
    ...

@router.put("/admin/interfaces/{id}")
async def update_interface_permission(
    id: int,
    request: InterfacePermissionUpdate,
):
    """更新接口权限配置"""
    ...

@router.delete("/admin/interfaces/{id}")
async def delete_interface_permission(id: int):
    """删除接口权限配置"""
    ...

@router.get("/admin/interfaces/unconfigured")
async def list_unconfigured_interfaces():
    """获取未配置的接口（用于快速配置）"""
    # 扫描所有路由，筛选未在 interface_permissions 表中配置的接口
    ...
```

### 6.4 权限命名规范

建议采用 `资源:操作` 格式：

| 权限代码 | 说明 |
|---------|------|
| `user:create` | 创建用户 |
| `user:read` | 查看用户 |
| `user:update` | 修改用户 |
| `user:delete` | 删除用户 |
| `user:*` | 用户相关所有权限 |
| `role:create` | 创建角色 |
| `role:assign` | 分配角色 |
| `role:*` | 角色相关所有权限 |
| `*` | 全部权限（仅 system_users） |

---

## 七、核心流程

### 7.1 请求处理流程

```
POST /api/users
     │
     ▼
┌─────────────────────────────────────────────────────────────────┐
│ 1. AuthMiddleware                                                │
│    - 从 Header 读取 Bearer Token                                 │
│    - 解码 JWT 获取用户信息                                        │
│    - ContextVar.set(user)                                        │
└─────────────────────────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. PermissionMiddleware                                          │
│    - 查 bypass_paths 表：/api/users 是否需要跳过？                 │
│      → 否                                                        │
│    - 查 interface_permissions 表：POST /api/users 需要什么权限？  │
│      → "user:create"                                             │
│    - ContextVar.get() 获取用户权限                                │
│      → ["user:read", "user:create"]                              │
│    - 检查："user:create" in ["user:read", "user:create"]？        │
│      → 是，有权限                                                 │
└─────────────────────────────────────────────────────────────────┘
     │
     ▼
    业务处理（Controller/Service）
```

### 7.2 system_user 请求流程

```
POST /api/users (admin 用户)
     │
     ▼
AuthMiddleware → ContextVar.set({ username: "admin", permissions: ["*"] })
     │
     ▼
PermissionMiddleware
     │
     ├── 检查 is_system_user("admin") → True
     │
     ▼
直接放行（绕过权限检查）
```

---

## 八、前端权限应用

### 8.1 后端接口鉴权

使用动态中间件后，**后端接口无需写权限代码**，权限由数据库配置。

### 8.2 前端按钮权限控制

```vue
<template>
  <!-- 只有拥有 user:delete 权限才显示删除按钮 -->
  <el-button 
    v-if="hasPermission('user:delete')" 
    type="danger"
    @click="handleDelete"
  >
    删除用户
  </el-button>
  
  <!-- 使用权限指令 -->
  <el-button v-permission="'user:create'" type="primary">
    新建用户
  </el-button>
</template>

<script setup>
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()

// 检查是否有指定权限
const hasPermission = (code) => {
  return userStore.permissions.includes('*') || 
         userStore.permissions.includes(code)
}
</script>
```

### 8.3 前端路由守卫

```js
// src/router/index.js
const routes = [
  {
    path: '/admin',
    component: AdminLayout,
    children: [
      { 
        path: 'users', 
        component: UserList, 
        meta: { 
          title: '用户管理',
          permissions: ['user:read', 'user:create', 'user:update', 'user:delete']
        } 
      },
    ]
  }
]

// 路由守卫
router.beforeEach((to, from, next) => {
  const userStore = useUserStore()
  const requiredPermissions = to.meta.permissions || []
  
  // system_users (permissions=["*"]) 直接通过
  if (userStore.permissions.includes('*')) {
    return next()
  }
  
  // 检查是否有权限
  const hasPermission = requiredPermissions.some(p => 
    userStore.permissions.includes(p)
  )
  
  if (hasPermission) {
    next()
  } else {
    next('/403')
  }
})
```

### 8.4 菜单动态生成

```js
// 根据权限动态生成菜单
const generateMenus = (allMenus, permissions) => {
  return allMenus.filter(menu => {
    // 无权限要求，直接显示
    if (!menu.requiredPermission) return true
    
    // system_users 显示所有菜单
    if (permissions.includes('*')) return true
    
    // 检查权限
    return permissions.includes(menu.requiredPermission)
  })
}
```

### 8.5 权限层级总结

| 层级 | 作用 | 重要性 |
|------|------|--------|
| **后端接口** | 真正的安全防护，阻止非法请求 | ⭐⭐⭐ 核心 |
| **前端按钮** | 体验优化，隐藏无权操作的按钮 | ⭐⭐ 重要 |
| **前端路由** | 体验优化，阻止访问无权限的页面 | ⭐⭐ 重要 |
| **前端菜单** | 根据权限动态展示可用菜单 | ⭐ 辅助 |

> **注意**：核心永远是后端接口鉴权，前端只是辅助提升用户体验。攻击者可以绕过前端直接调用后端 API。

---

## 九、备选方案：手动 Depends

如果不需要动态配置，可以使用传统的 Depends 方式：

### 9.1 deps.py

```python
# src/app/deps.py
from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from src.app.context import get_current_user
from src.services.rbac_service import RbacService


def require_permission(*required_permissions: str):
    """细粒度权限检查装饰器"""
    async def checker(user: CurrentUser = Depends(get_current_user)):
        # 1. 白名单用户 - 永远直接通过
        if RbacService.is_system_user(user.username):
            return user
        
        # 2. 普通用户 - 从 ContextVar 获取权限
        from src.app.context import get_user_permissions
        user.permissions = get_user_permissions()
        
        # 3. 检查权限
        if "*" in user.permissions or any(p in user.permissions for p in required_permissions):
            return user
        raise HTTPException(status_code=403, detail="权限不足")
    return checker
```

### 9.2 业务接口

```python
# 需要在代码中声明权限
@router.post("/users")
async def create_user(
    user: CurrentUser = Depends(require_permission("user:create")),
):
    ...
```

---

## 十、登录流程

### 10.1 普通用户登录

```
用户登录 → AuthService.authenticate() → 验证密码
                                         │
                                         ▼
                              RbacService.get_user_roles()
                                         │
                                         ▼
                              返回用户信息和角色
```

### 10.2 system_user 登录

```
用户登录 → AuthService.authenticate() → 验证密码
                                         │
                                         ▼
                              检查 is_system_user(username)
                                         │
                                         ▼
                              permissions = ["*"] (自动授予)
```

### 10.3 登录接口示例

```python
# src/app/routes/auth.py
@router.post("/login")
async def login(
    request: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    # 1. 认证
    user = await AuthService.authenticate(db, request.username, request.password)
    
    # 2. 检查是否为 system_user
    is_system = RbacService.is_system_user(user.username)
    
    # 3. 获取权限
    if is_system:
        permissions = ["*"]
        roles = ["system"]
    else:
        roles = await RbacService.get_user_roles(db, user.id)
        permissions = await RbacService.get_user_permissions(db, user.id)
    
    # 4. 生成 Token（包含权限信息，供中间件使用）
    token = create_access_token({
        "sub": user.username,
        "user_id": user.id,
        "roles": roles,
        "permissions": permissions,
    })
    
    return {
        "token": token,
        "user": {
            "id": user.id,
            "username": user.username,
            "roles": roles,
            "permissions": permissions,
        }
    }
```

---

## 十一、实现清单

### 11.1 数据库修改

- [ ] 创建 `interface_permissions` 表
- [ ] 创建 `bypass_paths` 表
- [ ] 初始化默认数据

### 11.2 后端修改

- [ ] 创建 `src/app/context.py` - ContextVar 用户上下文
- [ ] 创建 `src/app/middleware/auth_middleware.py` - 认证中间件
- [ ] 创建 `src/app/middleware/permission_middleware.py` - 权限校验中间件
- [ ] 修改 `src/main.py` - 注册中间件
- [ ] 创建 `src/app/routes/admin/interface_permission.py` - 管理端 API

### 11.3 前端修改

- [ ] 添加权限指令 `v-permission`
- [ ] 添加权限检查函数 `hasPermission()`
- [ ] 添加路由守卫权限检查
- [ ] 菜单根据权限动态生成
- [ ] 添加接口权限配置页面

---

## 十二、配置示例

### 12.1 环境变量

```bash
# .env
SYSTEM_ACCOUNTS=admin,system,backup
```

### 12.2 初始化数据

```python
# src/scripts/init_rbac.py

# 系统账户白名单
SYSTEM_ACCOUNTS = ["admin", "system"]

# 初始化权限
PERMISSIONS = [
    ("user:create", "创建用户"),
    ("user:read", "查看用户"),
    ("user:update", "修改用户"),
    ("user:delete", "删除用户"),
    ("user:*", "用户管理全部权限"),
    ("role:create", "创建角色"),
    ("role:read", "查看角色"),
    ("role:update", "修改角色"),
    ("role:delete", "删除角色"),
    ("role:assign", "分配角色"),
    ("role:*", "角色管理全部权限"),
]

# 初始化角色
ROLES = [
    ("admin", "管理员", "系统管理员"),
    ("operator", "操作员", "普通操作员"),
    ("viewer", "查看者", "只读用户"),
]

# 初始化接口权限配置
INTERFACE_PERMISSIONS = [
    ("/api/auth/login", "POST", None, "登录接口"),
    ("/api/auth/logout", "POST", None, "登出接口"),
    ("/api/users", "GET", "user:read", "查询用户列表"),
    ("/api/users", "POST", "user:create", "创建用户"),
    ("/api/users/{id}", "PUT", "user:update", "更新用户"),
    ("/api/users/{id}", "DELETE", "user:delete", "删除用户"),
    ("/api/roles", "GET", "role:read", "查询角色列表"),
    ("/api/roles", "POST", "role:create", "创建角色"),
]

# 初始化 bypass 路径（无需权限的接口）
BYPASS_PATHS = [
    ("/api/auth/login", "*", "登录接口"),
    ("/api/auth/register", "*", "注册接口"),
    ("/health", "*", "健康检查"),
    ("/docs", "*", "API 文档"),
    ("/openapi.json", "*", "OpenAPI 规范"),
]
```

---

## 十三、组件实现详解

### 13.1 ContextVar（Python ThreadLocal）

```python
# src/app/context.py
"""
ContextVar - Python 3.7+ 异步安全的用户上下文存储
类似 Java 的 ThreadLocal，但支持异步
"""
from contextvars import ContextVar
from typing import Optional, Dict, Any, List

# 定义上下文变量，存储当前用户
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
    """清除当前用户（请求结束时调用，防止内存泄漏）"""
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
    """检查当前用户是否为 system_user"""
    from src.services.rbac_service import RbacService
    username = get_username()
    if not username:
        return False
    return RbacService.is_system_user(username)
```

**使用示例**：

```python
# 在业务代码中获取当前用户
from src.app.context import get_current_user, get_user_permissions

def some_service():
    user = get_current_user()
    if user:
        print(f"当前用户: {user['username']}")
    
    # 检查权限
    permissions = get_user_permissions()
    if "*" in permissions or "user:read" in permissions:
        # 有权限
        pass
```

### 13.2 AuthMiddleware（认证拦截器）

```python
# src/app/middleware/auth_middleware.py
"""
认证中间件 - 类似 Java 的 HandlerInterceptor.preHandle()
职责：
1. 放行白名单路径（登录、注册等）
2. 解析 JWT Token
3. 设置用户上下文到 ContextVar
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.app.context import set_current_user, clear_current_user
from src.infra.jwt import verify_token, JWTError


class AuthMiddleware(BaseHTTPMiddleware):
    """请求认证中间件"""
    
    # 白名单路径（无需认证的接口）
    BYPASS_PATHS = [
        "/api/auth/login",
        "/api/auth/register",
        "/health",
        "/docs",
        "/openapi.json",
    ]
    
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method
        
        # 1. 检查是否在白名单中
        if self._is_bypass_path(path):
            return await call_next(request)
        
        # 2. 非白名单接口，需要 Token
        auth_header = request.headers.get("Authorization", "")
        
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "请先登录"}
            )
        
        token = auth_header[7:]
        
        # 3. 解析 JWT
        try:
            payload = verify_token(token)
        except JWTError as e:
            return JSONResponse(
                status_code=401,
                content={"detail": f"Token 无效: {str(e)}"}
            )
        
        # 4. 构建用户对象
        user = {
            "user_id": payload.get("userId"),
            "username": payload.get("username", payload.get("sub", "")),
            "roles": payload.get("roles", []),
            "permissions": payload.get("permissions", []),
        }
        
        # 5. 检查是否为 system_user，授予全部权限
        from src.services.rbac_service import RbacService
        if RbacService.is_system_user(user["username"]):
            user["permissions"] = ["*"]
        
        # 6. 设置到 ContextVar
        set_current_user(user)
        
        try:
            # 7. 继续处理请求
            return await call_next(request)
        finally:
            # 8. 请求结束，清除上下文
            clear_current_user()
    
    def _is_bypass_path(self, path: str) -> bool:
        """检查路径是否在白名单中"""
        for bypass_path in self.BYPASS_PATHS:
            if path == bypass_path or path.startswith(bypass_path + "/"):
                return True
        return False
```

### 13.3 PermissionMiddleware（权限校验拦截器）

```python
# src/app/middleware/permission_middleware.py
"""
权限校验中间件 - 查表自动校验接口权限
职责：
1. 查询 interface_permissions 表获取接口需要的权限
2. 从 ContextVar 获取用户权限
3. 比较并校验
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from sqlalchemy import select

from src.app.context import get_current_user, get_user_permissions, is_system_user
from src.infra.database import async_session
from src.models.rbac import InterfacePermission


class PermissionMiddleware(BaseHTTPMiddleware):
    """权限校验中间件"""
    
    # 缓存已查询的接口权限
    _permission_cache: dict = {}
    
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method.upper()
        
        # 1. 查询接口需要的权限
        required_permission = await self._get_required_permission(path, method)
        
        # 2. 接口未配置权限要求，直接放行
        if not required_permission:
            return await call_next(request)
        
        # 3. 获取当前用户
        user = get_current_user()
        
        # 4. 未登录
        if not user:
            return JSONResponse(
                status_code=401,
                content={"detail": "请先登录"}
            )
        
        # 5. system_user 直接放行
        if is_system_user():
            return await call_next(request)
        
        # 6. 检查用户权限
        user_permissions = get_user_permissions()
        
        if self._has_permission(user_permissions, required_permission):
            return await call_next(request)
        
        # 7. 无权限，拒绝
        return JSONResponse(
            status_code=403,
            content={"detail": f"权限不足，需要: {required_permission}"}
        )
    
    async def _get_required_permission(self, path: str, method: str) -> str:
        """获取接口需要的权限"""
        cache_key = f"{method}:{path}"
        
        # 先查缓存
        if cache_key in self._permission_cache:
            return self._permission_cache[cache_key]
        
        # 查数据库
        async with async_session() as db:
            result = await db.execute(
                select(InterfacePermission).where(
                    InterfacePermission.path == path,
                    InterfacePermission.method == method,
                    InterfacePermission.is_active == True
                )
            )
            interface_perm = result.scalar_one_or_none()
        
        permission = interface_perm.required_permission if interface_perm else None
        
        # 缓存
        self._permission_cache[cache_key] = permission
        return permission
    
    def _has_permission(self, user_permissions: list, required: str) -> bool:
        """检查是否有权限"""
        return "*" in user_permissions or required in user_permissions
```

### 13.4 JWT 组件

```python
# src/infra/jwt.py
"""
JWT Token 处理
类似 Java 的 JJWT 库
"""
from datetime import datetime, timedelta
from jose import jwt, JWTError
from src.infra.config import get_settings

settings = get_settings()

ALGORITHM = "HS256"


def create_token(data: dict, expires_delta: timedelta = None) -> str:
    """创建 JWT Token"""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=24)
    
    to_encode.update({"exp": expire})
    
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> dict:
    """验证并解析 JWT Token"""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError as e:
        raise JWTError(f"Token 验证失败: {str(e)}")


class JWTError(Exception):
    """JWT 异常"""
    pass
```

### 13.5 RBAC 组件

```python
# src/services/rbac_service.py
"""
RBAC 权限服务
职责：
1. 检查是否为 system_user
2. 查询用户角色
3. 查询用户权限
"""
from typing import List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infra.config import get_settings
from src.models.user import User
from src.models.rbac import Role, UserRole, Permission, RolePermission

settings = get_settings()


class RbacService:
    """RBAC 权限服务"""
    
    @staticmethod
    def is_system_user(username: str) -> bool:
        """检查是否为系统用户（白名单）"""
        return username in settings.SYSTEM_ACCOUNTS
    
    @staticmethod
    async def get_user_roles(db: AsyncSession, user_id: int) -> List[str]:
        """获取用户的所有角色代码"""
        result = await db.execute(
            select(Role.code)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
        )
        return [row[0] for row in result.fetchall()]
    
    @staticmethod
    async def get_user_permissions(db: AsyncSession, user_id: int) -> List[str]:
        """获取用户的所有权限代码"""
        result = await db.execute(
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .where(UserRole.user_id == user_id)
        )
        return [row[0] for row in result.fetchall()]
```

### 13.6 注册中间件

```python
# src/main.py
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from src.app.middleware.auth_middleware import AuthMiddleware
from src.app.middleware.permission_middleware import PermissionMiddleware

app = FastAPI(...)

# 注册中间件（顺序很重要！后添加的先执行）
# 1. CORSMiddleware 最先
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. PermissionMiddleware - 权限校验
app.add_middleware(PermissionMiddleware)

# 3. AuthMiddleware - 认证，最后添加，最先执行
app.add_middleware(AuthMiddleware)

# 注册路由...
```

### 13.7 登录接口（硬编码处理）

```python
# src/app/routes/auth.py
"""
登录接口 - 特殊处理
不需要 ContextVar（还没登录），直接在接口内部处理认证
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from src.infra.database import get_db
from src.infra.jwt import create_token
from src.services.rbac_service import RbacService

router = APIRouter(prefix="/api/auth", tags=["认证"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(
    request: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    # 1. 查询用户
    from src.models.user import User
    user = await db.get(User, request.username)
    
    if not user or not verify_password(request.password, user.password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    # 2. 检查是否为 system_user
    is_system = RbacService.is_system_user(user.username)
    
    # 3. 获取权限
    if is_system:
        roles = ["system"]
        permissions = ["*"]
    else:
        roles = await RbacService.get_user_roles(db, user.id)
        permissions = await RbacService.get_user_permissions(db, user.id)
    
    # 4. 生成 Token（包含权限信息，供后续请求使用）
    token = create_token({
        "sub": user.username,
        "userId": user.id,
        "username": user.username,
        "roles": roles,
        "permissions": permissions,
    })
    
    return {
        "token": token,
        "user": {
            "id": user.id,
            "username": user.username,
            "roles": roles,
            "permissions": permissions,
        }
    }
```

### 13.8 业务接口（无需权限代码）

```python
# src/app/routes/user.py
"""
业务接口 - 无需写权限代码
权限由 PermissionMiddleware 自动校验
"""
from fastapi import APIRouter
from src.app.context import get_current_user

router = APIRouter(prefix="/api/users", tags=["用户"])


@router.get("")
async def list_users():
    """
    查询用户列表 - 权限由中间件自动校验
    无需 Depends(require_permission("user:read"))
    """
    current_user = get_current_user()
    # 直接使用当前用户
    print(f"当前用户: {current_user['username']}")
    
    # 业务逻辑
    ...


@router.post("")
async def create_user(request: CreateUserRequest):
    """
    创建用户 - 权限由中间件自动校验
    """
    # 无需写权限代码
    ...


@router.put("/{user_id}")
async def update_user(user_id: int, request: UpdateUserRequest):
    """
    更新用户 - 权限由中间件自动校验
    """
    ...


@router.delete("/{user_id}")
async def delete_user(user_id: int):
    """
    删除用户 - 权限由中间件自动校验
    """
    ...
```

---

## 十四、Java vs Python 对照表

| 功能 | Java 实现 | Python 实现 |
|------|----------|------------|
| **上下文存储** | `ThreadLocal<User>` | `ContextVar[dict]` |
| **请求拦截** | `HandlerInterceptor` | `BaseHTTPMiddleware` |
| **权限注解** | `@RequiresPermissions("xxx")` | `interface_permissions` 表 |
| **注解扫描** | AOP 反射 | Middleware 查表 |
| **JWT 库** | JJWT | python-jose |
| **密码加密** | BCrypt | bcrypt |

### Java 代码示例

```java
// Java - ThreadLocal
public class UserContext {
    private static final ThreadLocal<User> currentUser = new ThreadLocal<>();
    
    public static void set(User user) { currentUser.set(user); }
    public static User get() { return currentUser.get(); }
    public static void clear() { currentUser.remove(); }
}

// Java - Interceptor
@Component
public class AuthInterceptor implements HandlerInterceptor {
    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
        String token = request.getHeader("Authorization");
        
        // 白名单放行
        if (isBypassPath(request.getRequestURI())) {
            return true;
        }
        
        // 解析 JWT
        User user = jwtService.parseToken(token);
        UserContext.set(user);
        
        return true;
    }
    
    @Override
    public void afterCompletion(...) {
        UserContext.clear();
    }
}

// Java - 权限注解
@RestController
public class UserController {
    @PostMapping("/users")
    @RequiresPermissions("user:create")
    public Response createUser(@RequestBody UserRequest request) {
        // 业务逻辑
    }
}
```

---

## 版本历史

| 版本 | 日期 | 说明 |
|------|------|------|
| v2.0 | 2026-07-02 | 初始版本，整合白名单 + RBAC 设计 |
| v2.1 | 2026-07-02 | 新增动态中间件方案，支持管理端配置接口权限 |
| v2.2 | 2026-07-02 | 新增组件实现详解，Java/Python 对照表 |
