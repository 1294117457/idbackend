# RBAC 最终设计文档

> 适用项目：`idpython` / `idfrontend` / `idfrontend-admin`
>
> 目标：统一说明本项目最终采用的 RBAC 方案、职责边界、缓存策略、白名单策略、鉴权流程、数据库结构和登录入口规则。
>
> 本文是最终版设计说明，仅用于确认方案，不包含代码修改。

---

## 1. 设计目标

本项目的 RBAC 设计目标是：

1. 用标准 RBAC 模型管理权限关系
2. 实现接口级鉴权
3. 支持 Redis 缓存，提高鉴权性能
4. 支持权限变更后即时生效
5. 支持公开接口白名单
6. 支持系统账号后门白名单
7. 支持后续扩展到菜单权限、按钮权限、数据权限

---

## 2. 最终采用的权限模型

### 2.1 基础关系

```text
User -> Role -> Permission -> Backend API
```

### 2.2 数据职责

- `User`：系统用户
- `Role`：角色，例如 `super_admin`、`admin`、`reviewer`、`user`
- `Permission`：权限点，例如 `review:approve`、`apply:create`
- `UserRole`：用户与角色的关联表
- `RolePermission`：角色与权限的关联表

### 2.3 权限码格式

统一使用：

```text
resource:action
```

示例：

- `user:create`
- `user:read`
- `user:update`
- `user:delete`
- `role:assign`
- `review:approve`
- `apply:my`

---

## 3. 最终职责划分

### 3.1 `AuthMiddleware`

`AuthMiddleware` 只负责**认证**，也就是“你是谁，你有没有登录”。

它处理：

- 路径白名单
- 读取并校验 JWT
- token 过期 / 无效判断
- 401 返回
- 将用户信息写入请求上下文

它**不负责**：

- 角色判断
- 权限判断
- 后门账号放行

### 3.2 `PermissionMiddleware`

`PermissionMiddleware` 只负责**授权**，也就是“你能不能访问这个接口”。

它处理：

- 读取当前请求的 method + 路径
- 查接口对应的 permission
- 查用户角色 / 权限
- 判断是否允许访问
- 返回 403
- 处理后门账号白名单

它**不负责**：

- token 解析
- 登录态校验
- 401 返回

---

## 4. 白名单最终定义

白名单分成两类，不能混用。

### 4.1 路径白名单

放在 `AuthMiddleware`。

适用于：无需登录即可访问的接口。

例如：

- `/api/auth/login`
- `/api/auth/register`
- `/api/auth/captcha`
- `/health`
- `/docs`
- `/openapi.json`

这类接口属于“认证豁免”，不需要 token。

### 4.2 后门账户白名单

放在 `PermissionMiddleware` 或 `RbacService`。

适用于：已经登录，但在授权层直接放行的系统账号。

例如：

- 超级管理员
- 运维账号
- 紧急恢复账号

这类账号属于“授权豁免”，仍然需要登录，但不受普通权限限制。

### 4.3 白名单命名建议

建议明确区分：

- `AUTH_WHITELIST`：路径白名单
- `SUPERUSER_WHITELIST`：系统账号白名单

不要把两者统称为一个“白名单”，否则容易把认证和授权混在一起。

---

## 5. 401 与 403 的最终规则

### 5.1 401 Unauthorized

由 `AuthMiddleware` 返回。

触发场景：

- 没有 token
- token 格式不正确
- token 过期
- token 无效

### 5.2 403 Forbidden

由 `PermissionMiddleware` 返回。

触发场景：

- 已登录，但没有对应 permission
- 已登录，但角色不满足要求
- 已登录，但不是后门白名单账号

### 5.3 最终原则

- **未登录 / 登录失败 → 401**
- **已登录但无权限 → 403**

这是最清晰的职责边界。

---

## 6. 登录入口设计

### 6.1 统一原则

后台登录不交给 `PermissionMiddleware`，而是在登录服务中做入口准入判断。

### 6.2 `LoginService.login_for_admin()`

`adminlogin` 的特殊鉴权统一放在：

- `LoginService.login_for_admin()`

该方法负责：

1. 校验用户名和密码
2. 查询用户角色
3. 判断用户是否拥有允许后台登录的系统角色
4. 允许则签发 token
5. 不允许则返回 403

### 6.3 后台允许登录的角色

建议定义后台登录角色集合，例如：

- `super_admin`
- `admin`
- `reviewer`

`user` 默认不允许进入后台管理登录入口。

### 6.4 为什么不放进 `PermissionMiddleware`

因为 `adminlogin` 发生在登录前，通常还没有 token，也没有当前用户上下文。

`PermissionMiddleware` 依赖“已登录用户”的身份信息，因此不适合处理这个场景。

---

## 7. 请求处理流程

### 7.1 总流程

```text
Request
  -> AuthMiddleware
  -> PermissionMiddleware
  -> Business Handler
```

### 7.2 登录流程

```text
adminlogin 请求
  -> LoginService.login_for_admin()
  -> 校验账号密码
  -> 查用户角色
  -> 判断是否允许后台登录
  -> 生成 token
```

### 7.3 详细流程

1. 请求进入系统
2. `AuthMiddleware` 判断是否为路径白名单
3. 如果是公开接口，直接放行
4. 否则校验 token
5. token 无效则返回 401
6. token 有效则写入用户上下文
7. 请求继续进入 `PermissionMiddleware`
8. `PermissionMiddleware` 先判断是否为免权限接口
9. 若不是免权限接口，查询该接口对应的 permission
10. 查询当前用户权限集合
11. 若用户是后门白名单账号，直接放行
12. 若用户拥有该 permission，放行
13. 否则返回 403

---

## 8. Redis 缓存策略

### 8.1 缓存目标

Redis 用于缓存：

- 用户角色
- 用户权限
- 接口与权限映射

### 8.2 推荐 Key

- `rbac:user:roles:{user_id}`
- `rbac:user:perms:{user_id}`
- `rbac:api:{method}:{normalized_path}`

### 8.3 接口权限映射值

建议使用明确状态，而不是只存空值。

可取值：

- `PUBLIC`
- `UNCONFIGURED`
- `permission_code`

### 8.4 缓存规则

- Redis 命中优先使用缓存
- Redis miss 回源数据库
- 数据库有结果则回填 Redis
- 权限变更后主动删除相关缓存

---

## 9. 数据库结构最终设计

> 结论：**需要微调数据库表结构**。
>
> 目前已有 `users / role / permission / user_role / role_permission` 五张核心表，能支撑基础 RBAC。
> 但如果要完整实现“权限绑定后端接口、Redis 接口映射、权限动态更新”这套方案，建议对表结构做如下最终调整。

### 9.1 最终建议的核心表

#### 9.1.1 `users`

现有表可继续使用。

不新增 `is_super_admin` 字段。

系统账号后门白名单继续通过配置文件或环境变量维护，不落库。

建议保留字段：

- `id`
- `username`
- `password`
- `phone`
- `avatar`
- `status`
- `last_login_at`
- 其他业务字段保持不变

#### 9.1.2 `role`

现有表可继续使用。

建议字段：

- `id`
- `role_code`
- `role_name`
- `description`
- `sort_order`
- `status`
- `is_system`
- `created_at`
- `updated_at`

#### 9.1.3 `permission`

这是最终需要重点调整的表。

最终字段设计如下：

- `id`
- `permission_code`
- `permission_name`
- `api_path`
- `description`
- `sort_order`
- `status`

说明：

- `permission_code`：权限编码，如 `review:approve`
- `permission_name`：权限名称，如 `通过审核`
- `api_path`：绑定的后端接口路径，如 `/api/review/{id}/approve`
- `description`：权限说明
- `sort_order`：排序
- `status`：启用 / 停用

> 说明：当前文档最终采用这一套字段，不再拆分 `http_method`、`module`、`parent_id`、`is_menu`。

#### 9.1.4 `user_role`

现有关联表可继续使用。

建议增加：

- 唯一约束 `(user_id, role_id)`
- 索引 `user_id`
- 索引 `role_id`

#### 9.1.5 `role_permission`

现有关联表可继续使用。

建议增加：

- 唯一约束 `(role_id, permission_id)`
- 索引 `role_id`
- 索引 `permission_id`

---

### 9.2 是否需要新增“接口映射表”

最终结论：**不新增 `permission_api` 表**。

原因：

- 你的平台当前复杂度不需要额外拆表
- `permission` 表直接带 `api_path` 已够用
- 实现和维护成本更低

如果未来出现“一权限绑定多个接口”的复杂需求，再考虑扩展。

---

### 9.3 最终推荐表结构汇总

#### `users`

- `id`
- `username`
- `password`
- `phone`
- `avatar`
- `status`
- `last_login_at`
- 其他业务字段保持不变

#### `role`

- `id`
- `role_code`
- `role_name`
- `description`
- `sort_order`
- `status`
- `is_system`

#### `permission`

- `id`
- `permission_code`
- `permission_name`
- `api_path`
- `description`
- `sort_order`
- `status`

#### `user_role`

- `id`
- `user_id`
- `role_id`
- `created_at`
- `updated_at`

#### `role_permission`

- `id`
- `role_id`
- `permission_id`
- `created_at`
- `updated_at`

---

## 10. 数据库约束建议

建议补充以下约束：

1. `users.username` 唯一
2. `role.role_code` 唯一
3. `permission.permission_code` 唯一
4. `user_role(user_id, role_id)` 唯一
5. `role_permission(role_id, permission_id)` 唯一
6. `permission.api_path` 建议建立索引

---

## 11. 数据字段设计建议

### 11.1 `permission.api_path`

建议存标准化路径，例如：

- `/api/system/role`
- `/api/system/role/{id}`
- `/api/review/{id}/approve`

### 11.2 `permission.permission_code`

建议保持稳定，例如：

- `role:read`
- `role:create`
- `review:approve`
- `apply:create`

### 11.3 `permission.permission_name`

用于管理后台展示，例如：

- `查看角色`
- `创建角色`
- `通过审核`
- `提交申请`

### 11.4 `status`

建议保持启用 / 停用控制，停用后：

- 不再参与新授权
- 中间件可忽略失效权限

---

## 12. 是否必须立刻改表

### 12.1 必须改的点

如果要严格落地“接口级权限绑定”，那么至少建议将 `permission` 表字段规范为：

- `id`
- `permission_code`
- `permission_name`
- `api_path`
- `description`
- `sort_order`
- `status`

### 12.2 可以后置的点

以下可以先不改：

- 更复杂的菜单树结构
- `permission_api`
- `users.is_super_admin`
- `http_method`
- `module`
- `parent_id`
- `is_menu`

### 12.3 推荐策略

- **短期**：沿用现有表 + 统一 `permission` 表字段
- **中期**：补约束、索引、缓存刷新机制
- **长期**：如接口复杂度增加，再考虑拆分更复杂表结构

---

## 13. 最终结论

### 13.1 需要修改数据库表吗？

**需要小幅调整，但不做复杂拆表。**

当前最终建议是：

1. `permission` 表统一为 7 个字段：
   - `id`
   - `permission_code`
   - `permission_name`
   - `api_path`
   - `description`
   - `sort_order`
   - `status`
2. `users` 不增加 `is_super_admin`
3. 不新增 `permission_api`
4. `user_role`、`role_permission` 增加唯一约束

### 13.2 最终建议

对于你当前的平台，推荐采用：

- `User -> Role -> Permission` 作为主关系
- `Permission` 表直接存接口路径
- `AuthMiddleware` 管认证
- `PermissionMiddleware` 管授权
- 后门账号白名单放授权层
- Redis 缓存接口映射和用户权限
- 权限更新立即刷新缓存
- `adminlogin` 的入口准入判断放在 `LoginService.login_for_admin()`

---

## 14. 接口绑定方案（M4）

### 14.1 设计思路

管理端创建/编辑权限时，通过接口获取后端所有路由，管理员手动选择绑定。

**不采用**定时扫描自动入库，原因：
- 权限需要人工梳理，不能随意自动生成
- 可能产生大量无意义的 permission 记录
- 管理员应完全控制权限表内容

### 14.2 核心接口

#### 获取所有可用接口

```
GET /api/system/permission/interfaces
```

响应示例：

```json
{
  "code": 0,
  "data": [
    { "path": "/api/system/role/list", "method": "GET",    "code": "role:read",   "label": "[GET] /api/system/role/list" },
    { "path": "/api/system/role/create", "method": "POST",  "code": "role:create", "label": "[POST] /api/system/role/create" },
    { "path": "/api/system/role/update", "method": "PUT",   "code": "role:update", "label": "[PUT] /api/system/role/update" },
    { "path": "/api/applications",       "method": "GET",   "code": "applications:read",  "label": "[GET] /api/applications" },
    { "path": "/api/applications",       "method": "POST",  "code": "applications:create", "label": "[POST] /api/applications" },
    ...
  ]
}
```

#### 扫描并生成权限代码建议

```
POST /api/system/permission/scan-interfaces
```

响应示例：

```json
{
  "code": 0,
  "data": {
    "count": 48,
    "permissions": [
      { "path": "/api/system/role/list",   "method": "GET",    "code": "role:read" },
      { "path": "/api/system/role/create", "method": "POST",   "code": "role:create" },
      ...
    ]
  }
}
```

### 14.3 权限码提取规则

`_extract_permission_code(path, method)` 的逻辑：

1. 路径去掉前缀 `/`
2. 跳过 `system`、`api` 等前缀目录
3. 跳过路径参数（如 `{id}`）和纯数字段
4. 取最后一个有意义的路径段作为 `resource`
5. 根据 HTTP 方法映射 `action`：
   - `GET` → `read`
   - `POST` → `create`
   - `PUT` / `PATCH` → `update`
   - `DELETE` → `delete`

示例：

| 路径 | 方法 | 提取结果 |
|------|------|----------|
| `/api/system/role/list` | GET | `role:read` |
| `/api/system/role/create` | POST | `role:create` |
| `/api/applications/{id}` | DELETE | `applications:delete` |
| `/api/users/profile` | PUT | `users:update` |

### 14.4 管理端工作流

```
1. 管理员进入权限管理页面
2. 点击「新建权限」
3. 前端调用 GET /api/system/permission/interfaces 获取所有接口列表
4. 管理员从列表中选择要绑定的接口（或手动输入 permission_code）
5. 填写权限名称、描述
6. 提交创建请求 POST /api/system/permission/create
   - body: { permissionCode, permissionName, apiPath, description }
7. 权限创建成功，绑定到对应的 role
```

---

## 15. 相关文档

- [RBAC 接口鉴权方案文档](./rbac-middleware-implementation-plan.md)
- [RBAC 架构设计图](./rbac-architecture-diagram.md)
- [RBAC 开发实施清单](./rbac-development-checklist.md)
- [RBAC 接口与权限码规范](./rbac-interface-and-permission-code-spec.md)
