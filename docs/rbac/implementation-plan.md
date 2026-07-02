# RBAC 权限功能完善方案

> 文档版本: v2.1
> 创建日期: 2026-07-02
> 更新日期: 2026-07-02
> 适用工程: idpython (FastAPI)

---

## 零、SuperAdmin 白名单机制（核心设计）

> **设计目标**：实现"特定用户拥有全部权限"的需求，同时保持代码的隐蔽性。

### 0.1 设计原则

| 原则 | 说明 |
|------|------|
| 隐蔽性 | 不新增数据库字段，不暴露"超级管理员"字样 |
| 简洁性 | 仅在 RBAC 核心服务中加几行判断逻辑 |
| 兼容性 | 不影响现有 RBAC 体系的正常运行 |
| 可控性 | 白名单配置在代码/配置文件中，可随时修改 |

### 0.2 实现原理

```
┌─────────────────────────────────────────────────────────────┐
│                  RbacService.get_user_permissions()          │
│                                                             │
│   1. 查询用户信息                                            │
│   2. 检查用户名是否在白名单中                                  │
│                      │                                      │
│          ┌───────────┴───────────┐                          │
│        Yes                      No                           │
│          │                        │                          │
│          ▼                        ▼                          │
│   ┌─────────────┐          ┌──────────────┐                 │
│   │ return ["*"]│          │ 正常查询权限 │                 │
│   │ 全部权限    │          │ 返回实际权限  │                 │
│   └─────────────┘          └──────────────┘                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 0.3 白名单配置

**配置文件** (`src/infra/config.py`)：

```python
# 环境配置
class Settings(BaseSettings):
    # ... 其他配置 ...

    # ========== 系统内置账户白名单 ==========
    # 看起来像普通系统配置，没有"super"字样
    SYSTEM_ACCOUNTS: list = ["admin"]
```

**核心服务** (`src/services/rbac_service.py`)：

```python
class RbacService:
    """RBAC 核心服务（含 SuperAdmin 白名单）"""

    @staticmethod
    async def get_user_permissions(user_id: int, settings=None) -> List[str]:
        """获取用户权限（含 SuperAdmin 自动扩展）"""

        # 1. 查询用户
        user = await db.get(User, user_id)
        if not user:
            return []

        # 2. 【关键】检查是否在白名单中
        admin_users = settings.SYSTEM_ACCOUNTS if settings else []
        if user.username in admin_users:
            return ["*"]  # 返回所有权限

        # 3. 普通用户走标准 RBAC
        return await RbacService._query_user_permissions(user_id)

    @staticmethod
    async def is_admin_user(user_id: int, settings=None) -> bool:
        """判断是否是管理员用户"""
        user = await db.get(User, user_id)
        if not user:
            return False
        admin_users = settings.SYSTEM_ACCOUNTS if settings else []
        return user.username in admin_users
```

### 0.4 数据库视角

白名单机制**不需要修改数据库**，数据库中完全看不到任何异常：

```sql
-- users 表（看起来完全正常）
SELECT * FROM users;
┌────┬──────────┬─────────────────────┐
│ id │ username │ password            │
├────┼──────────┼─────────────────────┤
│  1 │ admin    │ $2b$12$hashed...   │ ← 看起来就是普通管理员
└────┴──────────┴─────────────────────┘

-- 没有任何 super_admin、is_superuser 等特殊字段
```

### 0.5 使用方式

| 操作 | 步骤 |
|------|------|
| 添加超级管理员 | 在 `SYSTEM_ACCOUNTS` 中添加用户名 |
| 移除超级管理员 | 从 `SYSTEM_ACCOUNTS` 中删除用户名 |
| 生效方式 | 重启服务即可 |

### 0.6 与普通 RBAC 的关系

```
┌─────────────────────────────────────────────────────────────┐
│                       权限获取流程                           │
│                                                             │
│  用户请求权限                                                │
│       │                                                     │
│       ▼                                                     │
│  ┌─────────────────┐                                       │
│  │ 白名单检查       │ ←── 新增逻辑                          │
│  │ (username in    │                                       │
│  │  SYSTEM_ACCOUNTS│                                       │
│  └────────┬────────┘                                       │
│           │                                                 │
│     ┌─────┴─────┐                                           │
│   Yes          No                                          │
│     │           │                                          │
│     ▼           ▼                                          │
│  ┌──────┐  ┌────────────────────┐                          │
│  │["*"] │  │ 查询 role_permission│                          │
│  │全部  │  │ 返回实际权限列表    │                          │
│  └──────┘  └────────────────────┘                          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 一、现状分析

### 1.1 已有数据表

`idpython` 项目中已定义完整的 RBAC 模型（`src/models/user.py`）：

| 表名 | 用途 | 状态 | 说明 |
|------|------|------|------|
| `users` | 用户表 | ⚠️ 待优化 | 含冗余 role 字符串字段 |
| `role` | 角色表 | ✅ 已有 | 含 role_code, role_name 等 |
| `permission` | 权限表 | ⚠️ 待优化 | 缺少树形和菜单字段 |
| `user_role` | 用户-角色关联表 | ✅ 已有 | user_id, role_id |
| `role_permission` | 角色-权限关联表 | ✅ 已有 | role_id, permission_id |

### 1.2 User 模型现状

**当前问题：**

```73:83:src/models/user.py
class User(Base, TimestampMixin):
    """用户表"""
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(15))
    avatar: Mapped[Optional[str]] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default=UserStatus.ACTIVE.value)
    role: Mapped[str] = mapped_column(String(50), default="user")  # ⚠️ 冗余字段
    last_login_at: Mapped[Optional[str]] = mapped_column(String(50))
```

| 字段 | 类型 | 问题 | 优化建议 |
|------|------|------|---------|
| `role` | String(50) | ❌ 冗余 | **废弃**，通过 `roles` 关系获取 |
| `roles` | relationship | ✅ 正确 | 多对多关联 Role 表 |
| `status` | String(20) | ⚠️ 可优化 | 可改为 Boolean 或 Enum |

**为什么 role 字段冗余？**

```
User.role (字符串) ❌                      User.roles (关系) ✅
     │                                           │
     ▼                                           ▼
  "admin"  ← 只存单个角色                 [Role(id=1, code="admin"), ...]
                                               │
                                        通过 user_role 表关联
```

### 1.3 Permission 模型现状

```54:70:src/models/user.py
class Permission(Base, TimestampMixin):
    """权限表"""
    __tablename__ = "permission"

    permission_code: Mapped[str] = mapped_column(...)
    permission_name: Mapped[str] = mapped_column(...)
    module: Mapped[str] = mapped_column(...)
    description: Mapped[Optional[str]] = mapped_column(...)
    sort_order: Mapped[int] = mapped_column(...)
    status: Mapped[bool] = mapped_column(...)
    # ❌ 缺少 parent_id (树形结构)
    # ❌ 缺少 is_menu (菜单标识)
    # ❌ 缺少 api_path (API 路径)
    # ❌ 缺少 icon (菜单图标)
```

| 缺失字段 | 用途 | 优先级 | 影响 |
|---------|------|--------|------|
| `parent_id` | 树形菜单结构 | P1 | 前端动态菜单 |
| `is_menu` | 是否显示为菜单 | P1 | 菜单渲染 |
| `api_path` | 关联的 API 路径 | P2 | 按钮权限控制 |
| `icon` | 菜单图标 | P2 | UI 展示 |

### 1.4 Role 模型现状

```34:51:src/models/user.py
class Role(Base, TimestampMixin):
    """角色表"""
    __tablename__ = "role"

    role_code: Mapped[str] = mapped_column(...)
    role_name: Mapped[str] = mapped_column(...)
    description: Mapped[Optional[str]] = mapped_column(...)
    sort_order: Mapped[int] = mapped_column(...)
    status: Mapped[bool] = mapped_column(...)
    is_system: Mapped[bool] = mapped_column(...)  # ✅ 系统角色标识
```

**状态：✅ 可直接使用，无需修改**

### 1.2 现有代码问题

| 问题 | 位置 | 描述 |
|------|------|------|
| 权限检查简陋 | `src/app/deps.py` | 仅支持简单角色字符串匹配 |
| 无 RBAC Service | - | 缺少权限校验核心服务 |
| 无 Redis 缓存 | - | 缺少用户权限缓存机制 |
| API 不完整 | `src/app/routes/user.py` | 角色分配接口 TODO 未实现 |
| 前端对接缺失 | - | 缺少前端期望的 `/api/system/role/*` 等接口 |

### 1.3 前端期望的 API

前端 `idfrontend-admin/src/api/modules/apiRBAC.ts` 期望的接口：

**角色管理**
| 接口 | 方法 | 功能 |
|------|------|------|
| `/api/system/role/list` | GET | 获取角色列表 |
| `/api/system/role/{id}` | GET | 获取角色详情 |
| `/api/system/role/create` | POST | 创建角色 |
| `/api/system/role/update` | PUT | 更新角色 |
| `/api/system/role/{id}` | DELETE | 删除角色 |
| `/api/system/role/{roleId}/permissions` | GET | 获取角色权限 |
| `/api/system/role/assignPermissions` | POST | 分配权限 |

**权限管理**
| 接口 | 方法 | 功能 |
|------|------|------|
| `/api/system/permission/list` | GET | 获取权限列表 |
| `/api/system/permission/module/{module}` | GET | 按模块获取权限 |
| `/api/system/permission/create` | POST | 创建权限 |
| `/api/system/permission/update` | PUT | 更新权限 |
| `/api/system/permission/{id}` | DELETE | 删除权限 |

---

## 二、实现方案

### 2.1 技术架构

```
┌─────────────────────────────────────────────────────────┐
│                      API Layer                          │
│  /api/system/role/*    /api/system/permission/*       │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│                    Service Layer                        │
│  RbacService: 权限校验、角色管理、权限管理              │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│                    Model Layer                          │
│  User, Role, Permission, UserRole, RolePermission      │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│                    Cache Layer (Redis)                  │
│  用户角色缓存 (30分钟) / 用户权限缓存 (30分钟)          │
└─────────────────────────────────────────────────────────┘
```

### 2.2 目录结构

```
src/
├── services/
│   └── rbac_service.py      # 【新增】RBAC 核心服务
├── app/
│   ├── routes/
│   │   ├── role.py          # 【新增】角色管理 API
│   │   └── permission.py    # 【新增】权限管理 API
│   └── deps.py              # 【修改】新增权限检查装饰器
├── models/
│   └── user.py              # 【优化】可选扩展字段
└── main.py                  # 【修改】注册新路由
```

### 2.3 核心依赖

无需新增额外依赖，已使用的：
- `sqlalchemy` - ORM
- `python-jose` - JWT
- `redis` - Redis 缓存

---

## 三、详细设计

### 3.1 RBAC 核心服务 (rbac_service.py)

**文件路径**: `src/services/rbac_service.py`

```python
class RbacService:
    """RBAC 核心服务"""
    
    CACHE_TTL = 30  # 缓存过期时间(分钟)
    USER_ROLES_KEY = "rbac:user:roles:"
    USER_PERMS_KEY = "rbac:user:perms:"
    
    # ==================== 权限校验 ====================
    
    async def get_user_roles(user_id: int) -> List[str]:
        """获取用户角色列表（含缓存）"""
        
    async def get_user_permissions(user_id: int) -> List[str]:
        """获取用户权限列表（含缓存）"""
        
    async def has_any_role(user_id: int, *roles: str) -> bool:
        """检查用户是否拥有指定角色（任意一个）"""
        
    async def has_permission(user_id: int, permission_code: str) -> bool:
        """检查用户是否拥有指定权限"""
        
    async def clear_user_cache(user_id: int):
        """清除用户缓存"""
        
    # ==================== 角色管理 ====================
    
    async def create_role(...) -> Role:
        """创建角色"""
        
    async def update_role(...) -> Role:
        """更新角色"""
        
    async def delete_role(role_id: int) -> bool:
        """删除角色（检查是否系统角色、是否有用户使用）"""
        
    async def get_role_permissions(role_id: int) -> List[Permission]:
        """获取角色权限"""
        
    async def assign_permissions(role_id: int, permission_ids: List[int]):
        """分配权限给角色"""
        
    # ==================== 权限管理 ====================
    
    async def create_permission(...) -> Permission:
        """创建权限"""
        
    async def update_permission(...) -> Permission:
        """更新权限"""
        
    async def delete_permission(permission_id: int) -> bool:
        """删除权限"""
        
    # ==================== 用户角色分配 ====================
    
    async def assign_roles(user_id: int, role_ids: List[int]):
        """分配角色给用户"""
        
    async def get_user_role_ids(user_id: int) -> List[int]:
        """获取用户角色ID列表"""
```

### 3.2 依赖注入升级 (deps.py)

```python
from src.services.rbac_service import RbacService

@dataclass
class CurrentUser:
    """当前登录用户（增强版）"""
    user_id: int
    username: str
    role: str
    role_codes: List[str] = field(default_factory=list)  # 新增
    permissions: List[str] = field(default_factory=list)  # 新增


def require_permission(*required_permissions: str):
    """权限检查装饰器"""
    async def checker(
        user: CurrentUser = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> CurrentUser:
        # 从数据库获取最新权限
        permissions = await RbacService.get_user_permissions(user.user_id)
        if not any(p in permissions for p in required_permissions):
            raise HTTPException(status_code=403, detail="权限不足")
        user.permissions = permissions
        return user
    return checker


def require_role(*allowed_roles: str):
    """角色检查装饰器（增强版，支持角色编码）"""
    # ... 支持 role_code 匹配
```

### 3.3 API 路由设计

**角色管理路由** (`src/app/routes/role.py`)

```python
router = APIRouter(prefix="/api/system/role", tags=["角色管理"])

@router.get("/list")
async def get_role_list(
    db: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(require_admin),
):
    """获取角色列表"""
    
@router.post("/create")
async def create_role(
    data: RoleCreate,
    db: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(require_admin),
):
    """创建角色"""
    
@router.put("/update")
async def update_role(...):
    """更新角色"""
    
@router.delete("/{role_id}")
async def delete_role(...):
    """删除角色（系统角色不可删除）"""
    
@router.get("/{role_id}/permissions")
async def get_role_permissions(...):
    """获取角色权限"""
    
@router.post("/assignPermissions")
async def assign_permissions_to_role(...):
    """分配权限给角色"""
```

**权限管理路由** (`src/app/routes/permission.py`)

```python
router = APIRouter(prefix="/api/system/permission", tags=["权限管理"])

@router.get("/list")
async def get_permission_list(...):
    """获取权限列表"""
    
@router.get("/module/{module}")
async def get_permissions_by_module(...):
    """按模块获取权限"""
    
@router.post("/create")
async def create_permission(...):
    """创建权限"""
    
@router.put("/update")
async def update_permission(...):
    """更新权限"""
    
@router.delete("/{permission_id}")
async def delete_permission(...):
    """删除权限"""
```

---

## 四、数据表优化建议

### 4.1 User 表优化：废弃 role 冗余字段

**问题分析：**

当前 User 表存在 `role` 字符串字段，与 `roles` 多对多关系冲突。

**优化方案：**

```python
# src/models/user.py

class User(Base, TimestampMixin):
    """用户表（优化版）"""
    __tablename__ = "users"

    # ... 其他字段保持不变 ...
    
    # 删除 role: Mapped[str] = mapped_column(String(50), default="user")
    # ✅ 通过 roles 关系获取用户角色
    
    # 新增便捷属性
    @property
    def primary_role(self) -> Optional[str]:
        """获取主角色（第一个角色）"""
        if self.roles:
            return self.roles[0].role_code
        return None
    
    @property
    def role_codes(self) -> List[str]:
        """获取所有角色代码"""
        return [r.role_code for r in self.roles]
    
    @property
    def is_super_admin(self) -> bool:
        """是否超级管理员"""
        return "super_admin" in self.role_codes
```

**迁移步骤：**

```sql
-- 1. 确保所有用户都有角色关系
INSERT INTO user_role (user_id, role_id)
SELECT id, (SELECT id FROM role WHERE role_code = 'user')
FROM users 
WHERE id NOT IN (SELECT user_id FROM user_role);

-- 2. 验证迁移
SELECT COUNT(*) FROM user_role;

-- 3. 删除冗余字段（确认无误后）
ALTER TABLE users DROP COLUMN role;
```

**回滚方案：**

```sql
-- 如需回滚，执行以下语句
ALTER TABLE users ADD COLUMN role VARCHAR(50) DEFAULT 'user';
UPDATE users SET role = (SELECT role_code FROM role LIMIT 1);
```

### 4.2 Permission 表优化：树形结构

**目标：** 支持无限层级的菜单树结构

```python
# src/models/user.py

class Permission(Base, TimestampMixin):
    """权限表（优化版 - 支持树形结构）"""
    __tablename__ = "permission"

    permission_code: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False
    )
    permission_name: Mapped[str] = mapped_column(String(100), nullable=False)
    module: Mapped[str] = mapped_column(String(50), nullable=False)
    
    # ========== 树形结构字段 ==========
    parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("permission.id", ondelete="SET NULL")
    )  # 父级权限 ID，NULL 表示顶级
    level: Mapped[int] = mapped_column(Integer, default=1)  # 层级深度
    path: Mapped[str] = mapped_column(String(500), default="")  # 路径，如 "/1/2/3/"
    
    # ========== 菜单相关字段 ==========
    is_menu: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否菜单
    icon: Mapped[Optional[str]] = mapped_column(String(100))  # 菜单图标
    route_path: Mapped[Optional[str]] = mapped_column(String(255))  # 路由路径
    component_path: Mapped[Optional[str]] = mapped_column(String(255))  # 组件路径
    
    # ========== API 相关字段 ==========
    api_method: Mapped[Optional[str]] = mapped_column(String(10))  # GET/POST/PUT/DELETE
    api_path: Mapped[Optional[str]] = mapped_column(String(255))  # API 路径
    
    # ========== 其他字段 ==========
    description: Mapped[Optional[str]] = mapped_column(String(255))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[bool] = mapped_column(Boolean, default=True)

    # 关系
    roles: Mapped[List["Role"]] = relationship(
        "Role", secondary="role_permission", back_populates="permissions"
    )
    
    # 树形关系
    parent: Mapped[Optional["Permission"]] = relationship(
        "Permission", remote_side="Permission.id", back_populates="children"
    )
    children: Mapped[List["Permission"]] = relationship(
        "Permission", back_populates="parent", cascade="all, delete-orphan"
    )
```

**树形结构示例：**

```
permission_code          parent_id    level    path         is_menu
─────────────────────────────────────────────────────────────────────
system                   NULL          1       /1/          true
├── user_management      1             2       /1/2/        true
│   ├── user:view       2             3       /1/2/3/      false
│   ├── user:create     2             3       /1/2/4/      false
│   └── user:delete     2             3       /1/2/5/      false
└── role_management     1             2       /1/6/        true
    ├── role:view       7             3       /1/6/7/      false
    └── role:edit       7             3       /1/6/8/      false
```

**树形查询方法：**

```python
# src/services/rbac_service.py

class PermissionService:
    """权限服务（包含树形操作）"""
    
    @staticmethod
    async def get_permission_tree(db: AsyncSession) -> List[dict]:
        """获取完整权限树"""
        result = await db.execute(
            select(Permission).where(Permission.status == True).order_by(Permission.sort_order)
        )
        permissions = result.scalars().all()
        return PermissionService._build_tree(permissions)
    
    @staticmethod
    def _build_tree(permissions: List[Permission]) -> List[dict]:
        """递归构建树形结构"""
        permission_dict = {p.id: p for p in permissions}
        tree = []
        
        for p in permissions:
            if p.parent_id is None:
                tree.append(PermissionService._to_dict(p, permission_dict))
        
        return tree
    
    @staticmethod
    def _to_dict(permission: Permission, permission_dict: dict) -> dict:
        """将权限转换为字典（包含 children）"""
        children = [
            PermissionService._to_dict(p, permission_dict)
            for p in permission_dict.values()
            if p.parent_id == permission.id
        ]
        
        return {
            "id": permission.id,
            "permission_code": permission.permission_code,
            "permission_name": permission.permission_name,
            "module": permission.module,
            "is_menu": permission.is_menu,
            "icon": permission.icon,
            "route_path": permission.route_path,
            "children": sorted(children, key=lambda x: x.get("sort_order", 0))
        }
    
    @staticmethod
    async def get_children_ids(db: AsyncSession, permission_id: int) -> List[int]:
        """获取所有子权限 ID（包含自己）"""
        permission = await db.get(Permission, permission_id)
        if not permission:
            return []
        
        # 使用 path 查询所有子节点
        result = await db.execute(
            select(Permission.id).where(Permission.path.like(f"{permission.path}%"))
        )
        return list(result.scalars().all())
```

### 4.3 迁移脚本

**迁移文件：** `migrations/001_optimize_rbac_tables.py`

```python
"""迁移脚本：优化 RBAC 表结构

Revision ID: 001
Revises: 
Create Date: 2026-07-02

Operations:
1. User 表：删除冗余 role 字段
2. Permission 表：添加树形结构字段
3. 创建必要索引
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ========== User 表优化 ==========
    # 注意：此操作需要先确保 user_role 表有数据
    # 建议分步执行，见 4.1 节的 SQL 脚本
    
    # op.drop_column('users', 'role')  # 确认无误后执行
    
    # ========== Permission 表优化 ==========
    op.add_column('permission', sa.Column('parent_id', sa.Integer(), sa.ForeignKey('permission.id', ondelete='SET NULL'), nullable=True))
    op.add_column('permission', sa.Column('level', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('permission', sa.Column('path', sa.String(500), nullable=False, server_default=''))
    op.add_column('permission', sa.Column('is_menu', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('permission', sa.Column('icon', sa.String(100), nullable=True))
    op.add_column('permission', sa.Column('route_path', sa.String(255), nullable=True))
    op.add_column('permission', sa.Column('component_path', sa.String(255), nullable=True))
    op.add_column('permission', sa.Column('api_method', sa.String(10), nullable=True))
    op.add_column('permission', sa.Column('api_path', sa.String(255), nullable=True))
    
    # ========== 创建索引 ==========
    op.create_index('idx_permission_parent_id', 'permission', ['parent_id'])
    op.create_index('idx_permission_module', 'permission', ['module'])
    op.create_index('idx_permission_path', 'permission', ['path'])
    op.create_index('idx_user_role_composite', 'user_role', ['user_id', 'role_id'])
    op.create_index('idx_role_permission_composite', 'role_permission', ['role_id', 'permission_id'])


def downgrade() -> None:
    """回滚操作"""
    # 删除索引
    op.drop_index('idx_role_permission_composite')
    op.drop_index('idx_user_role_composite')
    op.drop_index('idx_permission_path')
    op.drop_index('idx_permission_module')
    op.drop_index('idx_permission_parent_id')
    
    # 删除 Permission 表字段
    op.drop_column('permission', 'api_path')
    op.drop_column('permission', 'api_method')
    op.drop_column('permission', 'component_path')
    op.drop_column('permission', 'route_path')
    op.drop_column('permission', 'icon')
    op.drop_column('permission', 'is_menu')
    op.drop_column('permission', 'path')
    op.drop_column('permission', 'level')
    op.drop_column('permission', 'parent_id')
    
    # 恢复 User 表字段（如果之前删除了）
    # op.add_column('users', sa.Column('role', sa.String(50), nullable=False, server_default='user'))
```

### 4.4 数据库索引建议

**必须创建的索引：**

```sql
-- Permission 表
CREATE INDEX idx_permission_parent_id ON permission(parent_id);
CREATE INDEX idx_permission_module ON permission(module);
CREATE INDEX idx_permission_path ON permission(path);
CREATE INDEX idx_permission_status ON permission(status);

-- Role 表
CREATE UNIQUE INDEX idx_role_code ON role(role_code);

-- User 表
CREATE UNIQUE INDEX idx_username ON users(username);
CREATE INDEX idx_user_status ON users(status);

-- 关联表
CREATE INDEX idx_user_role_user_id ON user_role(user_id);
CREATE INDEX idx_user_role_role_id ON user_role(role_id);
CREATE UNIQUE INDEX idx_user_role_composite ON user_role(user_id, role_id);

CREATE INDEX idx_role_permission_role_id ON role_permission(role_id);
CREATE INDEX idx_role_permission_permission_id ON role_permission(permission_id);
CREATE UNIQUE INDEX idx_role_permission_composite ON role_permission(role_id, permission_id);
```

---

## 五、默认数据初始化

### 5.1 角色数据

| role_code | role_name | description | is_system |
|------------|-----------|-------------|-----------|
| admin | 管理员 | 系统内置账户，通过白名单获得全部权限 | 1 |
| reviewer | 审核员 | 审核用户申请 | 1 |
| user | 普通用户 | 默认角色 | 1 |

**说明：** `admin` 用户通过白名单机制（`SYSTEM_ACCOUNTS`）自动获得全部权限，不需要在 `role_permission` 表中分配。

### 5.2 权限数据（树形结构）

**顶级模块：**

| id | permission_code | permission_name | parent_id | level | path | is_menu |
|----|-----------------|-----------------|-----------|-------|------|---------|
| 1 | system | 系统管理 | NULL | 1 | /1/ | true |
| 2 | user | 用户管理 | NULL | 1 | /2/ | true |
| 3 | role | 角色管理 | NULL | 1 | /3/ | true |
| 4 | template | 模板管理 | NULL | 1 | /4/ | true |
| 5 | demand | 需求管理 | NULL | 1 | /5/ | true |

**系统管理模块（parent_id=1）：**

| permission_code | permission_name | parent_id | level | is_menu | api_path |
|-----------------|-----------------|-----------|-------|---------|----------|
| system:view | 查看系统设置 | 1 | 2 | true | NULL |
| system:edit | 编辑系统设置 | 1 | 2 | false | /api/system/* |

**用户管理模块（parent_id=2）：**

| permission_code | permission_name | parent_id | level | is_menu | api_path |
|-----------------|-----------------|-----------|-------|---------|----------|
| user:view | 查看用户 | 2 | 2 | true | GET /api/user/* |
| user:create | 创建用户 | 2 | 2 | false | POST /api/user |
| user:edit | 编辑用户 | 2 | 2 | false | PUT /api/user/* |
| user:delete | 删除用户 | 2 | 2 | false | DELETE /api/user/* |

**角色管理模块（parent_id=3）：**

| permission_code | permission_name | parent_id | level | is_menu | api_path |
|-----------------|-----------------|-----------|-------|---------|----------|
| role:view | 查看角色 | 3 | 2 | true | GET /api/system/role/* |
| role:create | 创建角色 | 3 | 2 | false | POST /api/system/role/* |
| role:edit | 编辑角色 | 3 | 2 | false | PUT /api/system/role/* |
| role:delete | 删除角色 | 3 | 2 | false | DELETE /api/system/role/* |
| role:assign | 分配角色权限 | 3 | 2 | false | POST /api/system/role/assignPermissions |

**需求管理模块（parent_id=5）：**

| permission_code | permission_name | parent_id | level | is_menu | api_path |
|-----------------|-----------------|-----------|-------|---------|----------|
| demand:view | 查看需求 | 5 | 2 | true | GET /api/demand/* |
| demand:create | 创建需求 | 5 | 2 | false | POST /api/demand |
| demand:edit | 编辑需求 | 5 | 2 | false | PUT /api/demand/* |
| demand:review | 审核需求 | 5 | 2 | false | POST /api/demand/review |
| demand:delete | 删除需求 | 5 | 2 | false | DELETE /api/demand/* |

### 5.3 角色权限分配

| 角色 | 权限 | 说明 |
|------|------|------|
| admin | - | **通过白名单机制获取全部权限**，不需要分配 |
| reviewer | demand:view, demand:review | 审核权限 |
| user | demand:view, demand:create | 基本权限 |

### 5.4 种子数据脚本

```python
# src/scripts/init_rbac_data.py

async def init_rbac_data(db: AsyncSession):
    """初始化 RBAC 默认数据"""

    # 1. 创建角色
    # 注意：admin 角色不需要分配任何权限（通过白名单获取全部权限）
    roles = [
        Role(role_code="admin", role_name="管理员",
             description="系统内置账户，通过白名单获得全部权限", is_system=True, sort_order=1),
        Role(role_code="reviewer", role_name="审核员",
             description="审核用户申请", is_system=True, sort_order=2),
        Role(role_code="user", role_name="普通用户",
             description="默认角色", is_system=True, sort_order=3),
    ]
    db.add_all(roles)
    await db.flush()

    # 2. 创建权限（树形结构）
    permissions = [
        # 系统管理
        Permission(permission_code="system", permission_name="系统管理",
                   module="system", parent_id=None, level=1, path="/1/",
                   is_menu=True, sort_order=1),
        # 用户管理
        Permission(permission_code="user", permission_name="用户管理",
                   module="user", parent_id=None, level=1, path="/2/",
                   is_menu=True, sort_order=2),
        # ...
    ]

    await db.commit()
    print("RBAC 默认数据初始化完成")
    print("提示：admin 用户通过 SYSTEM_ACCOUNTS 配置获得全部权限")
```

---

## 六、实现计划

### Phase 1: 核心 RBAC 服务 ⭐
**目标**: 实现权限校验核心逻辑（含 SuperAdmin 白名单）

#### 1.1 配置白名单

在 `src/infra/config.py` 中添加配置：

```python
class Settings(BaseSettings):
    # ... 其他配置 ...

    # 系统内置账户白名单（拥有全部权限）
    SYSTEM_ACCOUNTS: list = ["admin"]
```

#### 1.2 创建 RbacService

新建 `src/services/rbac_service.py`：

```python
"""RBAC 核心服务"""
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.models.user import User, Role, Permission, UserRole, RolePermission
from src.infra.redis import get_redis, RedisCache
from src.infra.config import get_settings

settings = get_settings()


class RbacService:
    """RBAC 核心服务（含 SuperAdmin 白名单）"""

    CACHE_TTL = 30  # 缓存过期时间(分钟)
    USER_ROLES_KEY = "rbac:user:roles:"
    USER_PERMS_KEY = "rbac:user:perms:"

    # ========== SuperAdmin 白名单 ==========
    # 从配置读取，看起来像普通系统配置
    ADMIN_USERS: List[str] = []

    @classmethod
    def _get_admin_users(cls) -> List[str]:
        """获取管理员白名单"""
        if not cls.ADMIN_USERS:
            cls.ADMIN_USERS = settings.SYSTEM_ACCOUNTS
        return cls.ADMIN_USERS

    # ==================== 权限校验 ====================

    @staticmethod
    async def get_user_roles(user_id: int) -> List[str]:
        """获取用户角色列表（含缓存）"""
        redis = await get_redis()
        cache = RedisCache(redis)
        key = f"{RbacService.USER_ROLES_KEY}{user_id}"

        # 查缓存
        cached = await cache.get(key)
        if cached:
            return cached

        # 查数据库
        result = await db.execute(
            select(Role.role_code)
            .join(UserRole, Role.id == UserRole.role_id)
            .where(UserRole.user_id == user_id)
        )
        roles = list(result.scalars().all())

        # 写缓存
        await cache.setex(key, RbacService.CACHE_TTL * 60, roles)
        return roles

    @staticmethod
    async def get_user_permissions(user_id: int) -> List[str]:
        """获取用户权限列表（含缓存，含 SuperAdmin 自动扩展）"""

        # 1. 检查是否在白名单中
        user = await db.get(User, user_id)
        if not user:
            return []

        if user.username in RbacService._get_admin_users():
            return ["*"]  # 管理员拥有所有权限

        # 2. 普通用户走标准 RBAC
        redis = await get_redis()
        cache = RedisCache(redis)
        key = f"{RbacService.USER_PERMS_KEY}{user_id}"

        # 查缓存
        cached = await cache.get(key)
        if cached:
            return cached

        # 查数据库
        result = await db.execute(
            select(Permission.permission_code)
            .join(RolePermission, Permission.id == RolePermission.permission_id)
            .join(UserRole, RolePermission.role_id == UserRole.role_id)
            .where(UserRole.user_id == user_id)
            .where(Permission.status == True)
        )
        perms = list(set(result.scalars().all()))  # 去重

        # 写缓存
        await cache.setex(key, RbacService.CACHE_TTL * 60, perms)
        return perms

    @staticmethod
    async def has_permission(user_id: int, permission_code: str) -> bool:
        """检查用户是否拥有指定权限"""
        perms = await RbacService.get_user_permissions(user_id)
        return "*" in perms or permission_code in perms

    @staticmethod
    async def clear_user_cache(user_id: int):
        """清除用户缓存"""
        redis = await get_redis()
        cache = RedisCache(redis)
        await cache.delete(f"{RbacService.USER_ROLES_KEY}{user_id}")
        await cache.delete(f"{RbacService.USER_PERMS_KEY}{user_id}")

    @staticmethod
    async def is_admin_user(user_id: int) -> bool:
        """判断是否是管理员用户"""
        user = await db.get(User, user_id)
        if not user:
            return False
        return user.username in RbacService._get_admin_users()

    # ==================== 角色管理 ====================

    @staticmethod
    async def create_role(...) -> Role:
        """创建角色"""
        # ...

    @staticmethod
    async def update_role(...) -> Role:
        """更新角色"""
        # ...

    @staticmethod
    async def delete_role(role_id: int) -> bool:
        """删除角色（检查是否系统角色、是否有用户使用）"""
        # ...

    # ==================== 权限管理 ====================

    @staticmethod
    async def create_permission(...) -> Permission:
        """创建权限"""
        # ...

    @staticmethod
    async def update_permission(...) -> Permission:
        """更新权限"""
        # ...

    @staticmethod
    async def delete_permission(permission_id: int) -> bool:
        """删除权限"""
        # ...

    # ==================== 用户角色分配 ====================

    @staticmethod
    async def assign_roles(user_id: int, role_ids: List[int]):
        """分配角色给用户"""
        # ...

    @staticmethod
    async def get_user_role_ids(user_id: int) -> List[int]:
        """获取用户角色ID列表"""
        # ...
```

#### 1.3 升级依赖注入

修改 `src/app/deps.py`：

```python
from src.services.rbac_service import RbacService

@dataclass
class CurrentUser:
    """当前登录用户（增强版）"""
    user_id: int
    username: str
    role: str
    role_codes: List[str] = field(default_factory=list)  # 新增
    permissions: List[str] = field(default_factory=list)  # 新增


def require_permission(*required_permissions: str):
    """权限检查装饰器"""
    async def checker(
        user: CurrentUser = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> CurrentUser:
        # 从数据库获取最新权限（含 SuperAdmin 判断）
        permissions = await RbacService.get_user_permissions(user.user_id)
        user.permissions = permissions

        if not any(p in permissions for p in required_permissions):
            raise HTTPException(status_code=403, detail="权限不足")
        return user
    return checker


def require_role(*allowed_roles: str):
    """角色检查装饰器（增强版，支持角色编码）"""
    async def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        # 首先检查是否是管理员（白名单用户自动通过）
        if await RbacService.is_admin_user(user.user_id):
            return user

        # 检查角色列表
        user_roles = await RbacService.get_user_roles(user.user_id)
        if not any(r in user_roles for r in allowed_roles):
            raise HTTPException(status_code=403, detail="权限不足")
        return user
    return checker
```

#### Phase 1 任务清单

- [x] 在 `config.py` 添加 `SYSTEM_ACCOUNTS` 配置
- [ ] 新建 `src/services/rbac_service.py`
- [ ] 实现 `get_user_roles()` 和 `get_user_permissions()` 含 Redis 缓存
- [ ] 实现 `has_permission()` 和 `is_admin_user()` 校验方法
- [ ] 实现 `clear_user_cache()` 缓存清除
- [ ] 升级 `src/app/deps.py` 新增 `require_permission` 装饰器
- [ ] 升级 `require_role` 支持白名单用户自动通过

### Phase 2: 后台管理 API ⭐⭐
**目标**: 提供前端对接接口
- [ ] 新建 `src/app/routes/role.py` 角色管理 CRUD
- [ ] 新建 `src/app/routes/permission.py` 权限管理 CRUD
- [ ] 注册路由到 `src/main.py`
- [ ] 前端联调

### Phase 3: 用户角色分配 ⭐⭐⭐
**目标**: 完善用户角色关系
- [ ] 修改用户注册逻辑，自动分配 `user` 角色
- [ ] 实现用户角色分配 API
- [ ] 实现角色权限分配 API
- [ ] 修改 `AuthService` 支持角色列表

### Phase 4: 数据初始化 ⭐⭐⭐⭐
**目标**: 初始化默认数据
- [ ] 编写种子数据脚本
- [ ] 创建默认角色（admin, reviewer, user）
- [ ] 创建默认权限
- [ ] 分配默认权限

### Phase 5: 优化完善 ⭐⭐⭐⭐⭐

**目标**: 优化扩展功能

#### 5.1 Permission 表增加树形结构
- [ ] 添加 `parent_id`, `level`, `path` 字段
- [ ] 添加 `is_menu`, `icon`, `route_path` 字段
- [ ] 添加 `api_method`, `api_path` 字段
- [ ] 实现树形查询方法
- [ ] 实现递归删除（含子节点）

#### 5.2 动态菜单生成
- [ ] 实现 `get_user_menus(user_id)` 方法
- [ ] 根据用户权限动态生成菜单树
- [ ] 前端对接菜单 API

#### 5.3 操作日志记录
- [ ] 创建 `OperationLog` 模型
- [ ] 记录权限变更日志
- [ ] 记录敏感操作（删除角色、分配权限等）

```python
# 操作日志模型
class OperationLog(Base, TimestampMixin):
    __tablename__ = "operation_log"
    
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(50))  # create/update/delete
    target_type: Mapped[str] = mapped_column(String(50))  # role/permission/user
    target_id: Mapped[int] = mapped_column()
    detail: Mapped[Optional[str]] = mapped_column(JSON)
    ip_address: Mapped[Optional[str]] = mapped_column(String(50))
```

#### 5.4 权限变更通知
- [ ] 实现权限变更事件通知
- [ ] 清除相关用户缓存
- [ ] 支持 WebSocket 实时通知（可选）

```python
# 权限变更通知
async def on_permission_changed(user_id: int, role_id: int):
    """权限变更回调"""
    # 1. 清除用户缓存
    await RbacService.clear_user_cache(user_id)
    
    # 2. 记录操作日志
    await log_operation(user_id, "update", "role", role_id)
    
    # 3. 发送通知（如果开启）
    await notify_permission_changed(user_id)
```

#### 5.5 权限缓存预热
- [ ] 用户登录时预热权限缓存
- [ ] 后台任务定期刷新缓存
- [ ] 缓存预热状态监控

---

## 七、参考实现

### 7.1 Java 后台参考

`idbackend/RbacService.java` 已有成熟实现：

```java
public List<String> getUserRoles(Integer userId) {
    String key = USER_ROLES_KEY + userId;
    List<String> cachedRoles = redisUtil.getList(key);
    if (cachedRoles != null) return cachedRoles;
    
    List<String> roles = roleMapper.selectRoleCodesByUserId(userId);
    redisUtil.setList(key, roles, CACHE_EXPIRE, TimeUnit.MINUTES);
    return roles;
}
```

### 7.2 Python 对应实现

```python
class RbacService:
    USER_ROLES_KEY = "rbac:user:roles:"
    CACHE_TTL = 30
    
    @staticmethod
    async def get_user_roles(user_id: int) -> List[str]:
        redis = await get_redis()
        cache = RedisCache(redis)
        key = f"{RbacService.USER_ROLES_KEY}{user_id}"
        
        cached = await cache.get(key)
        if cached:
            return cached
        
        # 查数据库
        result = await db.execute(
            select(Role.role_code)
            .join(UserRole, Role.id == UserRole.role_id)
            .where(UserRole.user_id == user_id)
        )
        roles = list(result.scalars().all())
        
        # 写入缓存
        await cache.setex(key, RbacService.CACHE_TTL * 60, roles)
        return roles
```

---

## 八、测试用例

### 8.1 单元测试

```python
# tests/test_rbac_service.py

class TestRbacService:
    
    async def test_get_user_roles(self, db):
        """测试获取用户角色"""
        roles = await RbacService.get_user_roles(1)
        assert "user" in roles
    
    async def test_has_permission(self, db):
        """测试权限检查"""
        result = await RbacService.has_permission(1, "user:view")
        assert result is True
    
    async def test_admin_has_all_permissions(self, db):
        """测试管理员拥有所有权限"""
        result = await RbacService.has_permission(1, "system:edit")
        assert result is True
```

### 8.2 API 测试

```python
# tests/test_rbac_api.py

class TestRoleAPI:
    
    async def test_create_role_as_admin(self, client, admin_token):
        """管理员创建角色"""
        response = client.post(
            "/api/system/role/create",
            json={"roleCode": "test", "roleName": "测试角色"},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
    
    async def test_normal_user_cannot_create_role(self, client, user_token):
        """普通用户不能创建角色"""
        response = client.post(
            "/api/system/role/create",
            json={"roleCode": "test", "roleName": "测试角色"},
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403
```

---

## 九、注意事项

### 9.1 安全性

1. **管理员账户保护**: 禁止修改/删除白名单用户（`SYSTEM_ACCOUNTS`）
2. **系统角色保护**: 禁止修改 `is_system=True` 的角色权限
3. **自己不能删除自己**: 操作者不能删除自己的账户
4. **权限最小化**: 用户只应获得完成工作所需的最小权限

### 9.2 性能

1. **Redis 缓存**: 用户角色和权限信息缓存 30 分钟
2. **批量操作**: 角色权限分配使用批量操作减少数据库请求
3. **索引优化**: 确保 `user_role` 和 `role_permission` 表有适当索引

### 9.3 兼容性

1. **保持现有接口**: 不破坏现有 `/api/user/*` 等接口
2. **平滑迁移**: 现有用户自动分配默认角色
3. **前端适配**: 新 API 与前端期望格式一致

---

## 十、附录

### 10.1 相关文件

| 文件路径 | 说明 |
|----------|------|
| `src/models/user.py` | RBAC 模型定义 |
| `src/app/deps.py` | 依赖注入（含权限检查） |
| `src/services/auth_service.py` | 认证服务 |
| `src/app/routes/user.py` | 用户路由（角色相关待实现） |
| `src/infra/redis.py` | Redis 工具 |

### 10.2 前端对接

| 前端文件 | 说明 |
|----------|------|
| `idfrontend-admin/src/api/modules/apiRBAC.ts` | RBAC API 调用 |
| `idfrontend-admin/src/api/modules/apiUser.ts` | 用户 API 调用 |
| `idfrontend-admin/src/stores/profile.ts` | 用户状态管理 |

### 10.3 参考文档

- [FastAPI 权限最佳实践](https://fastapi.tiangolo.com/tutorial/security/)
- [RBAC 模型详解](https://en.wikipedia.org/wiki/Role-based_access_control)
- [SQLAlchemy 关系配置](https://docs.sqlalchemy.org/en/20/orm/relationships.html)
