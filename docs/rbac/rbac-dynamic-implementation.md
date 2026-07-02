# RBAC 权限动态化改造方案

> 文档版本: v1.0
> 创建日期: 2026-07-02
> 适用工程: idpython (后端) + idfrontend-admin (前端)
> 目标: 实现权限的动态配置，替代前端硬编码的 `requiresRoles`

---

## 一、需求分析

### 1.1 业务场景

系统用于**学院保研加分工作**，用户角色分为：

| 角色代码 | 角色名称 | 说明 | 后台访问 |
|----------|----------|------|----------|
| `admin` | 管理员（老师） | 通过 `SYSTEM_ACCOUNTS=zch` 配置 | 全部功能 |
| `reviewer` | 审核员 | 审核学生提交的材料 | 仅审核相关页面 |
| `user` | 普通用户（学生） | 提交保研加分申请 | 受限功能 |

### 1.2 当前问题

1. **前端硬编码角色**: `requiresRoles: ['admin', 'super_admin']` 写死在路由配置中
2. **菜单过滤逻辑简单**: 仅基于角色名称匹配，无法精确控制按钮级权限
3. **缺少动态菜单 API**: 前端无法从后端获取用户实际可访问的菜单
4. **Permission 表字段不足**: 缺少菜单路由、组件路径等字段

---

## 二、后端改造方案

### 2.1 Permission 表扩展

**目标**: 支持菜单树的动态生成

**新增字段** (`src/models/user.py`):

```python
class Permission(Base, TimestampMixin):
    """权限表（扩展版 - 支持动态菜单）"""
    __tablename__ = "permission"

    # 现有字段...
    permission_code: Mapped[str] = mapped_column(...)
    permission_name: Mapped[str] = mapped_column(...)
    module: Mapped[str] = mapped_column(...)
    description: Mapped[Optional[str]] = mapped_column(...)
    sort_order: Mapped[int] = mapped_column(...)
    status: Mapped[bool] = mapped_column(...)

    # ========== 新增字段：菜单相关 ==========
    parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("permission.id", ondelete="SET NULL"),
        doc="父级权限ID，NULL表示顶级菜单"
    )
    is_menu: Mapped[bool] = mapped_column(Boolean, default=False, doc="是否显示为菜单")
    icon: Mapped[Optional[str]] = mapped_column(String(100), doc="菜单图标")
    route_path: Mapped[Optional[str]] = mapped_column(String(255), doc="前端路由路径")
    component_path: Mapped[Optional[str]] = mapped_column(String(255), doc="Vue组件路径")

    # 关系
    parent: Mapped[Optional["Permission"]] = relationship(
        "Permission", remote_side="Permission.id", back_populates="children"
    )
    children: Mapped[List["Permission"]] = relationship(
        "Permission", back_populates="parent", cascade="all, delete-orphan"
    )
```

### 2.2 初始化脚本完善

**文件**: `src/scripts/init_rbac_data.py`

**改进要点**:

1. 添加菜单相关字段 (`parent_id`, `is_menu`, `route_path`, `component_path`, `icon`)
2. 按业务场景初始化权限数据
3. 支持幂等执行（已存在则跳过）

**权限数据设计（保研加分场景）**:

```python
# 权限数据结构
permissions_data = [
    # ========== 一级菜单：账户管理 ==========
    {
        "permission_code": "account",
        "permission_name": "账户管理",
        "module": "account",
        "parent_id": None,
        "is_menu": True,
        "icon": "User",
        "route_path": "activity",
        "component_path": None,
        "sort_order": 5,
    },
    # 二级菜单
    {
        "permission_code": "account:view",
        "permission_name": "账户列表",
        "module": "account",
        "parent_id": None,  # 待查询
        "is_menu": True,
        "route_path": "activity/index",
        "component_path": "@/views/account-manage/index.vue",
        "sort_order": 1,
    },
    {
        "permission_code": "account:role",
        "permission_name": "角色管理",
        "module": "account",
        "parent_id": None,
        "is_menu": True,
        "route_path": "activity/role",
        "component_path": "@/views/account-manage/role.vue",
        "sort_order": 2,
    },
    {
        "permission_code": "account:permission",
        "permission_name": "权限管理",
        "module": "account",
        "parent_id": None,
        "is_menu": True,
        "route_path": "activity/permission",
        "component_path": "@/views/account-manage/permission.vue",
        "sort_order": 3,
    },

    # ========== 一级菜单：学生管理 ==========
    {
        "permission_code": "student",
        "permission_name": "学生管理",
        "module": "student",
        "parent_id": None,
        "is_menu": True,
        "icon": "School",
        "route_path": "student",
        "sort_order": 2,
    },
    {
        "permission_code": "student:view",
        "permission_name": "查看学生",
        "module": "student",
        "parent_id": None,
        "is_menu": True,
        "route_path": "student/index",
        "component_path": "@/views/student/index.vue",
        "sort_order": 1,
    },

    # ========== 一级菜单：审核管理 ==========
    {
        "permission_code": "review",
        "permission_name": "审核管理",
        "module": "review",
        "parent_id": None,
        "is_menu": True,
        "icon": "DocumentChecked",
        "route_path": "review",
        "sort_order": 3,
    },
    {
        "permission_code": "review:pending",
        "permission_name": "待审核",
        "module": "review",
        "parent_id": None,
        "is_menu": True,
        "route_path": "review/pending",
        "component_path": "@/views/review/pending.vue",
        "sort_order": 1,
    },
    {
        "permission_code": "review:approved",
        "permission_name": "已通过",
        "module": "review",
        "parent_id": None,
        "is_menu": True,
        "route_path": "review/approved",
        "component_path": "@/views/review/approved.vue",
        "sort_order": 2,
    },
    {
        "permission_code": "review:approve",
        "permission_name": "通过审核",
        "module": "review",
        "parent_id": None,
        "is_menu": False,  # 非菜单（按钮权限）
        "sort_order": 10,
    },
    {
        "permission_code": "review:reject",
        "permission_name": "拒绝审核",
        "module": "review",
        "parent_id": None,
        "is_menu": False,
        "sort_order": 11,
    },

    # ========== 一级菜单：加分申请（学生） ==========
    {
        "permission_code": "apply",
        "permission_name": "加分申请",
        "module": "apply",
        "parent_id": None,
        "is_menu": True,
        "icon": "FolderAdd",
        "route_path": "apply",
        "sort_order": 1,
    },
    {
        "permission_code": "apply:create",
        "permission_name": "提交申请",
        "module": "apply",
        "parent_id": None,
        "is_menu": True,
        "route_path": "apply/create",
        "component_path": "@/views/apply/create.vue",
        "sort_order": 1,
    },
    {
        "permission_code": "apply:my",
        "permission_name": "我的申请",
        "module": "apply",
        "parent_id": None,
        "is_menu": True,
        "route_path": "apply/my",
        "component_path": "@/views/apply/my.vue",
        "sort_order": 2,
    },

    # ========== 一级菜单：系统设置 ==========
    {
        "permission_code": "system",
        "permission_name": "系统设置",
        "module": "system",
        "parent_id": None,
        "is_menu": True,
        "icon": "Setting",
        "route_path": "system",
        "sort_order": 6,
    },
    {
        "permission_code": "system:view",
        "permission_name": "系统设置",
        "module": "system",
        "parent_id": None,
        "is_menu": True,
        "route_path": "system/index",
        "component_path": "@/views/system-settings/index.vue",
        "sort_order": 1,
    },
]
```

**角色权限分配**:

```python
# admin → 全部权限（通过 SYSTEM_ACCOUNTS）
# reviewer → student:view, review:*
# user → apply:*
```

### 2.3 动态菜单 API

**文件**: `src/app/routes/menu.py`（新建）

```python
"""用户菜单 API

提供当前用户可访问的动态菜单：
- GET /api/system/menu/my - 获取当前用户的菜单树
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from src.app.deps import get_db, get_current_user, CurrentUser
from src.services.rbac_service import RbacService

router = APIRouter(prefix="/api/system/menu", tags=["菜单管理"])


@router.get("/my")
async def get_my_menu(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的菜单树

    Returns:
        动态生成的菜单列表，仅包含用户有权限访问的菜单项
    """
    menus = await RbacService.get_user_menu_tree(db, current_user.user_id)
    return {"code": 200, "data": menus, "msg": "success"}
```

**Service 层方法** (`src/services/rbac_service.py`):

```python
@staticmethod
async def get_user_menu_tree(db: AsyncSession, user_id: int) -> List[dict]:
    """获取用户可访问的菜单树

    1. 获取用户权限列表
    2. 查询所有 is_menu=True 的权限
    3. 根据权限过滤，生成菜单树
    4. 管理员返回完整菜单

    Args:
        db: 数据库会话
        user_id: 用户ID

    Returns:
        菜单树列表
    """
    # 1. 获取用户权限
    user_permissions = await RbacService.get_user_permissions(db, user_id)

    # 2. 管理员返回完整菜单
    if "*" in user_permissions:
        result = await db.execute(
            select(Permission)
            .where(Permission.is_menu == True)
            .where(Permission.status == True)
            .order_by(Permission.sort_order)
        )
    else:
        # 3. 普通用户：根据权限过滤
        result = await db.execute(
            select(Permission)
            .where(Permission.is_menu == True)
            .where(Permission.status == True)
            .where(Permission.permission_code.in_(user_permissions))
            .order_by(Permission.sort_order)
        )

    permissions = result.scalars().all()

    # 4. 构建菜单树
    return RbacService._build_menu_tree(permissions)


@staticmethod
def _build_menu_tree(permissions: List[Permission]) -> List[dict]:
    """构建菜单树

    将扁平权限列表转换为树形结构
    """
    permission_dict = {p.id: p for p in permissions}
    tree = []

    for p in permissions:
        if p.parent_id is None:
            tree.append(RbacService._permission_to_menu(p, permission_dict))

    return tree


@staticmethod
def _permission_to_menu(permission: Permission, permission_dict: dict) -> dict:
    """将权限转换为菜单项"""
    children = [
        RbacService._permission_to_menu(p, permission_dict)
        for p in permission_dict.values()
        if p.parent_id == permission.id
    ]

    return {
        "id": permission.id,
        "permissionCode": permission.permission_code,
        "permissionName": permission.permission_name,
        "icon": permission.icon,
        "routePath": permission.route_path,
        "componentPath": permission.component_path,
        "sortOrder": permission.sort_order,
        "children": sorted(children, key=lambda x: x.get("sortOrder", 0)) if children else [],
    }
```

**API 响应示例**:

```json
{
  "code": 200,
  "data": [
    {
      "id": 1,
      "permissionCode": "account",
      "permissionName": "账户管理",
      "icon": "User",
      "routePath": "activity",
      "children": [
        {
          "id": 2,
          "permissionCode": "account:view",
          "permissionName": "账户列表",
          "routePath": "activity/index",
          "children": []
        }
      ]
    },
    {
      "id": 5,
      "permissionCode": "review",
      "permissionName": "审核管理",
      "icon": "DocumentChecked",
      "routePath": "review",
      "children": [...]
    }
  ],
  "msg": "success"
}
```

### 2.4 获取用户完整权限 API

**文件**: `src/app/routes/user.py`（新增端点）

```python
@router.get("/my/permissions")
async def get_my_permissions(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的所有权限列表

    用于前端按钮级权限控制
    """
    permissions = await RbacService.get_user_permissions(db, current_user.user_id)
    return {"code": 200, "data": permissions, "msg": "success"}
```

---

## 三、前端改造方案

### 3.1 目录结构

```
idfrontend-admin/src/
├── api/
│   └── modules/
│       └── apiMenu.ts          # 【新增】菜单 API
├── stores/
│   ├── profile.ts              # 【修改】添加 userMenus 状态
│   └── permission.ts           # 【新增】权限状态管理
├── router/
│   ├── index.ts               # 【修改】移除硬编码 requiresRoles
│   ├── dynamic.ts              # 【新增】动态路由加载
│   └── modules/
│       └── *.ts               # 【修改】移除 requiresRoles
└── common/
    └── directives/
        └── permission.ts       # 【新增】权限指令 v-permission
```

### 3.2 新增菜单 API

**文件**: `src/api/modules/apiMenu.ts`

```typescript
import http from '@/common/utils/http'

/**
 * 获取当前用户的菜单树
 */
export function getMyMenu() {
  return http.get<MenuItem[]>('/api/system/menu/my')
}

/**
 * 获取当前用户的所有权限
 */
export function getMyPermissions() {
  return http.get<string[]>('/api/system/user/my/permissions')
}

/**
 * 菜单项类型
 */
export interface MenuItem {
  id: number
  permissionCode: string
  permissionName: string
  icon?: string
  routePath?: string
  componentPath?: string
  sortOrder: number
  children?: MenuItem[]
}
```

### 3.3 权限状态管理

**文件**: `src/stores/permission.ts`（新建）

```typescript
import { defineStore } from 'pinia'
import { getMyMenu, getMyPermissions, type MenuItem } from '@/api/modules/apiMenu'

export const usePermissionStore = defineStore('permission', () => {
  // 菜单树
  const menus = ref<MenuItem[]>([])
  // 权限列表（按钮级）
  const permissions = ref<string[]>([])
  // 路由是否已加载
  const isLoaded = ref(false)

  /**
   * 加载用户权限和菜单
   */
  const loadPermissions = async () => {
    if (isLoaded.value) return

    try {
      const [menuRes, permRes] = await Promise.all([
        getMyMenu(),
        getMyPermissions(),
      ])

      menus.value = menuRes.data || []
      permissions.value = permRes.data || []
      isLoaded.value = true
    } catch (error) {
      console.error('加载权限失败:', error)
      menus.value = []
      permissions.value = []
    }
  }

  /**
   * 检查是否有指定权限
   */
  const hasPermission = (permission: string | string[]): boolean => {
    const perms = Array.isArray(permission) ? permission : [permission]
    return perms.some(p => permissions.value.includes(p) || permissions.value.includes('*'))
  }

  /**
   * 获取用户可访问的路由路径
   */
  const getAccessibleRoutes = (): string[] => {
    const routes: string[] = []

    const traverse = (items: MenuItem[]) => {
      for (const item of items) {
        if (item.routePath) {
          routes.push(item.routePath)
        }
        if (item.children?.length) {
          traverse(item.children)
        }
      }
    }

    traverse(menus.value)
    return routes
  }

  /**
   * 重置状态
   */
  const reset = () => {
    menus.value = []
    permissions.value = []
    isLoaded.value = false
  }

  return {
    menus,
    permissions,
    isLoaded,
    loadPermissions,
    hasPermission,
    getAccessibleRoutes,
    reset,
  }
})
```

### 3.4 路由守卫改造

**文件**: `src/router/index.ts`

**改造要点**:
1. 移除硬编码的 `requiresRoles` 检查
2. 改为从后端获取动态菜单/权限进行校验
3. 支持路由级别的权限控制

```typescript
import { createRouter, createWebHistory } from 'vue-router'
import { useUserStore } from '@/stores/profile'
import { usePermissionStore } from '@/stores/permission'
import { STORAGE_KEYS } from '@common/constants/storage'

import homeRoutes from './home'
import loginRoutes from './login'

const routes = [
  ...loginRoutes,
  homeRoutes,
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})

// 公开路由（无需权限）
const PUBLIC_ROUTES = ['/login', '/register', '/forgot', '/']

router.beforeEach(async (to) => {
  const token = localStorage.getItem(STORAGE_KEYS.ACCESS_TOKEN)
  const isPublicRoute = PUBLIC_ROUTES.includes(to.path)

  // 1. 公开路由直接放行
  if (isPublicRoute) {
    if (token && to.path === '/login') {
      return '/home/index'
    }
    return true
  }

  // 2. 未登录则跳转登录
  if (!token) {
    return '/login'
  }

  const userStore = useUserStore()
  const permissionStore = usePermissionStore()

  // 3. 获取用户基本信息
  if (!userStore.userInfo) {
    const success = await userStore.fetchUserData()
    if (!success) {
      userStore.clearAll()
      permissionStore.reset()
      return '/login'
    }
  }

  // 4. 【关键】加载用户权限和菜单
  await permissionStore.loadPermissions()

  // 5. 获取目标路由需要的权限
  const requiredPermission = to.meta?.requiresPermission as string | string[] | undefined

  if (requiredPermission) {
    // 有权限要求，检查是否满足
    if (!permissionStore.hasPermission(requiredPermission)) {
      console.warn(`访问 ${to.path} 权限不足`)
      return '/home/index'  // 无权限重定向到首页
    }
  }

  // 6. 通过所有检查
  return true
})

export default router
```

### 3.5 路由元信息改造

**文件**: `src/router/modules/account-manage.ts`

**改造前**（硬编码角色）:
```typescript
export default {
  path: 'activity',
  meta: { title: '账户管理', requiresRoles: ['admin', 'super_admin'] },
  // ...
}
```

**改造后**（使用权限代码）:
```typescript
export default {
  path: 'activity',
  meta: {
    title: '账户管理',
    requiresPermission: 'account:view',  // 使用权限代码
    icon: SettingIcon,
    sort: 5,
  },
  children: [
    { path: 'index', component: Account, meta: { title: '账户管理' } },
    { path: 'role', component: Role, meta: { title: '角色管理' } },
    { path: 'permission', component: Permission, meta: { title: '权限管理' } },
  ],
}
```

### 3.6 侧边栏菜单改造

**文件**: `src/views/home/component/SideMenu.vue`

**改造要点**:
1. 从 Permission Store 获取动态菜单
2. 移除基于硬编码 `requiresRoles` 的过滤逻辑

```vue
<template>
  <el-menu
    :default-active="activePath"
    :collapse="isCollapse"
    class="side-menu"
  >
    <template v-for="(item, index) in menuItems" :key="item.path + '-' + index">
      <!-- 子菜单 -->
      <el-sub-menu v-if="item.children?.length" :index="item.path">
        <template #title>
          <component v-if="item.meta?.icon" :is="item.meta.icon" class="w-5 h-5" />
          <span>{{ item.meta?.title }}</span>
        </template>
        <el-menu-item
          v-for="sub in item.children"
          :key="sub.path"
          :index="'/' + item.path + '/' + sub.path"
          @click="navigateTo('/home/' + item.path + '/' + sub.path)"
        >
          {{ sub.meta?.title }}
        </el-menu-item>
      </el-sub-menu>

      <!-- 单个菜单项 -->
      <el-menu-item v-else :index="'/' + item.path" @click="navigateTo('/home/' + item.path)">
        <component v-if="item.meta?.icon" :is="item.meta.icon" class="w-5 h-5" />
        <span>{{ item.meta?.title }}</span>
      </el-menu-item>
    </template>
  </el-menu>
</template>

<script lang="ts" setup>
import { computed, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { usePermissionStore } from '@/stores/permission'

const router = useRouter()
const route = useRoute()
const permissionStore = usePermissionStore()

// 获取路由配置中的所有菜单
const allMenuRoutes = computed(() => {
  const homeRoute = router.options.routes.find(r => r.path === '/home')
  return homeRoute?.children?.filter(r => !r.redirect && !r.meta?.hidden) || []
})

// 过滤后的菜单（基于权限）
const menuItems = computed(() => {
  return allMenuRoutes.value.filter(route => {
    const required = route.meta?.requiresPermission as string | string[] | undefined
    // 无权限要求，或有权限则显示
    if (!required) return true
    const perms = Array.isArray(required) ? required : [required]
    return perms.some(p => permissionStore.hasPermission(p))
  })
})

const activePath = ref(route.path.replace('/home/', ''))
const navigateTo = (path: string) => router.push(path)
</script>
```

### 3.7 权限指令（可选）

**文件**: `src/common/directives/permission.ts`

```typescript
import type { Directive } from 'vue'
import { usePermissionStore } from '@/stores/permission'

/**
 * v-permission 指令
 * 用法: <el-button v-permission="'user:create'">创建用户</el-button>
 *       <el-button v-permission="['user:edit', 'user:delete']">操作</el-button>
 */
export const permissionDirective: Directive = {
  mounted(el, binding) {
    const permissionStore = usePermissionStore()
    const value = binding.value

    if (value) {
      const hasPermission = Array.isArray(value)
        ? value.some(p => permissionStore.hasPermission(p))
        : permissionStore.hasPermission(value)

      if (!hasPermission) {
        el.style.display = 'none'
      }
    }
  },
}
```

**注册指令** (`main.ts`):

```typescript
import { permissionDirective } from '@/common/directives/permission'

app.directive('permission', permissionDirective)
```

---

## 四、数据库迁移

### 4.1 迁移脚本

**文件**: `migrations/001_add_menu_fields_to_permission.py`

```python
"""迁移脚本：Permission 表添加菜单相关字段

Revision ID: 001
Revises:
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa

revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 添加父级字段
    op.add_column('permission', sa.Column('parent_id', sa.Integer(),
                                           sa.ForeignKey('permission.id', ondelete='SET NULL'),
                                           nullable=True))
    # 添加菜单相关字段
    op.add_column('permission', sa.Column('is_menu', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('permission', sa.Column('icon', sa.String(100), nullable=True))
    op.add_column('permission', sa.Column('route_path', sa.String(255), nullable=True))
    op.add_column('permission', sa.Column('component_path', sa.String(255), nullable=True))

    # 创建索引
    op.create_index('idx_permission_parent_id', 'permission', ['parent_id'])
    op.create_index('idx_permission_is_menu', 'permission', ['is_menu'])


def downgrade() -> None:
    op.drop_index('idx_permission_is_menu')
    op.drop_index('idx_permission_parent_id')
    op.drop_column('permission', 'component_path')
    op.drop_column('permission', 'route_path')
    op.drop_column('permission', 'icon')
    op.drop_column('permission', 'is_menu')
    op.drop_column('permission', 'parent_id')
```

---

## 五、用户注册时自动分配角色

**文件**: `src/services/auth_service.py`（修改）

```python
@staticmethod
async def register(db: AsyncSession, username: str, password: str, email: str = None) -> User:
    """用户注册

    自动分配 'user' 角色
    """
    # ... 现有注册逻辑 ...

    # 自动分配默认角色
    result = await db.execute(
        select(Role).where(Role.role_code == "user")
    )
    default_role = result.scalar_one_or_none()

    if default_role:
        user_role = UserRole(user_id=user.id, role_id=default_role.id)
        db.add(user_role)

    await db.commit()
    await db.refresh(user)
    return user
```

---

## 六、实施步骤

| 阶段 | 步骤 | 后端 | 前端 | 说明 |
|------|------|------|------|------|
| **准备** | 1 | 修改 Permission 模型 | - | 添加菜单字段 |
| | 2 | 创建迁移脚本 | - | 数据库变更 |
| | 3 | - | 创建 apiMenu.ts | 菜单 API |
| | 4 | - | 创建 permission Store | 权限状态 |
| **后端** | 5 | 实现 get_user_menu_tree | - | 菜单树生成 |
| | 6 | 新建 menu.py 路由 | - | 菜单 API |
| | 7 | 完善 init_rbac_data.py | - | 初始化数据 |
| | 8 | 修改用户注册逻辑 | - | 自动分配角色 |
| **前端** | 9 | - | 改造路由守卫 | 动态权限 |
| | 10 | - | 移除硬编码 requiresRoles | 路由配置 |
| | 11 | - | 改造 SideMenu | 动态菜单 |
| | 12 | - | 创建权限指令 | 按钮控制 |
| **测试** | 13 | 运行迁移脚本 | - | 数据库变更 |
| | 14 | 运行初始化脚本 | - | 初始化权限数据 |
| | 15 | 测试各角色访问 | - | 验证权限控制 |

---

## 七、权限数据对照表

### 7.1 角色权限矩阵

| 功能 | admin | reviewer | user |
|------|:-----:|:--------:|:----:|
| 账户管理 | ✅ | ❌ | ❌ |
| 学生管理 | ✅ | ✅ | ❌ |
| 审核管理 | ✅ | ✅ | ❌ |
| 加分申请 | ✅ | ❌ | ✅ |
| 系统设置 | ✅ | ❌ | ❌ |

### 7.2 权限代码定义

| 权限代码 | 说明 | 适用角色 |
|----------|------|----------|
| `account:view` | 查看账户 | admin |
| `account:role` | 角色管理 | admin |
| `account:permission` | 权限管理 | admin |
| `student:view` | 查看学生 | admin, reviewer |
| `review:pending` | 待审核列表 | admin, reviewer |
| `review:approve` | 通过审核 | admin, reviewer |
| `review:reject` | 拒绝审核 | admin, reviewer |
| `apply:create` | 提交申请 | admin, user |
| `apply:my` | 我的申请 | admin, user |
| `system:view` | 系统设置 | admin |

---

## 八、注意事项

### 8.1 安全性

1. **后端必须校验**: 前端权限控制仅为 UX 优化，真正的安全校验在后端
2. **管理员保护**: `SYSTEM_ACCOUNTS` 中的用户自动拥有全部权限
3. **操作日志**: 建议记录权限变更操作

### 8.2 性能

1. **Redis 缓存**: 用户权限信息缓存 30 分钟
2. **菜单预加载**: 登录成功后预加载菜单，减少首次访问延迟
3. **按需加载**: 非菜单权限（如按钮权限）按需获取

### 8.3 兼容性

1. **现有数据**: 迁移脚本需要处理已存在的权限数据
2. **API 兼容**: 新增 API，不破坏现有接口
3. **前端适配**: 新 API 与前端期望格式保持一致

---

## 九、附录

### 9.1 相关文件清单

| 文件路径 | 操作 | 说明 |
|----------|------|------|
| `src/models/user.py` | 修改 | Permission 模型扩展 |
| `src/services/rbac_service.py` | 修改 | 添加菜单生成方法 |
| `src/app/routes/menu.py` | 新建 | 菜单 API |
| `src/app/routes/user.py` | 修改 | 添加权限查询接口 |
| `src/scripts/init_rbac_data.py` | 修改 | 完善初始化数据 |
| `src/services/auth_service.py` | 修改 | 注册时分配角色 |
| `migrations/001_*.py` | 新建 | 数据库迁移 |
| `idfrontend-admin/src/api/modules/apiMenu.ts` | 新建 | 菜单 API 调用 |
| `idfrontend-admin/src/stores/permission.ts` | 新建 | 权限状态管理 |
| `idfrontend-admin/src/router/index.ts` | 修改 | 路由守卫改造 |
| `idfrontend-admin/src/router/modules/*.ts` | 修改 | 移除硬编码角色 |
| `idfrontend-admin/src/views/home/component/SideMenu.vue` | 修改 | 动态菜单渲染 |
| `idfrontend-admin/src/common/directives/permission.ts` | 新建 | 权限指令 |
| `idfrontend-admin/src/main.ts` | 修改 | 注册指令 |

### 9.2 API 列表

| 接口 | 方法 | 说明 | 权限 |
|------|------|------|------|
| `/api/system/menu/my` | GET | 获取用户菜单树 | 登录用户 |
| `/api/system/user/my/permissions` | GET | 获取用户权限列表 | 登录用户 |
| `/api/system/role/list` | GET | 角色列表 | admin |
| `/api/system/permission/list` | GET | 权限列表 | admin |
