# RBAC 接口与权限码规范

> 目标：统一接口命名、权限码命名、缓存键命名和白名单分类，减少实现歧义。

---

## 1. 基本原则

1. 一个权限码表达一个清晰的业务能力
2. 权限码应稳定、可读、可扩展
3. 接口与权限的映射必须明确
4. 权限更新后应能快速同步到缓存
5. 白名单只能用于少量明确场景

---

## 2. 权限码命名规范

### 2.1 标准格式

```text
resource:action
```

### 2.2 推荐动作词

- `create`
- `read`
- `update`
- `delete`
- `manage`
- `assign`
- `approve`
- `reject`
- `export`
- `import`

### 2.3 示例

- `user:create`
- `user:read`
- `user:update`
- `user:delete`
- `role:read`
- `role:assign`
- `permission:manage`
- `review:approve`
- `review:reject`
- `apply:my`

---

## 3. 接口命名规范

### 3.1 REST 风格建议

- `GET /api/users`：查询列表
- `GET /api/users/{id}`：查询详情
- `POST /api/users`：创建
- `PUT /api/users/{id}`：更新
- `DELETE /api/users/{id}`：删除

### 3.2 后端路径规范

建议统一使用：

- `/api/system/...`：系统管理类
- `/api/auth/...`：认证类
- `/api/apply/...`：申请类
- `/api/review/...`：审核类
- `/api/student/...`：学生类

### 3.3 路由参数规范化

路径中如果包含参数，建议归一化为：

- `/api/users/{id}`
- `/api/review/{reviewId}`

不要直接把原始请求 URL 当成权限判断唯一键。

---

## 4. 接口与权限码映射规则

### 4.1 映射原则

一个接口可以：

- 对应一个权限码
- 或对应多个权限码中的一个

建议默认采用“一接口一权限码”，复杂场景再扩展。

### 4.2 推荐映射示例

| 接口 | 方法 | 建议权限码 |
|------|------|------------|
| `/api/system/role` | `GET` | `role:read` |
| `/api/system/role` | `POST` | `role:create` |
| `/api/system/role/{id}` | `PUT` | `role:update` |
| `/api/system/role/{id}` | `DELETE` | `role:delete` |
| `/api/system/role/{id}/permissions` | `PUT` | `role:assign` |
| `/api/system/permission` | `GET` | `permission:read` |
| `/api/system/permission` | `POST` | `permission:create` |
| `/api/system/permission/{id}` | `PUT` | `permission:update` |
| `/api/system/permission/{id}` | `DELETE` | `permission:delete` |
| `/api/review/pending` | `GET` | `review:pending` |
| `/api/review/{id}/approve` | `POST` | `review:approve` |
| `/api/review/{id}/reject` | `POST` | `review:reject` |
| `/api/apply/my` | `GET` | `apply:my` |
| `/api/apply` | `POST` | `apply:create` |

---

## 5. 权限分类规范

### 5.1 系统类权限

用于系统管理：

- 角色管理
- 权限管理
- 账户管理
- 系统配置

示例：

- `system_config:view`
- `account:assign_role`
- `permission:manage`

### 5.2 业务类权限

用于核心业务：

- 学生申请
- 审核
- 模板管理

示例：

- `apply:create`
- `apply:my`
- `review:approve`
- `template:create`

### 5.3 数据查看类权限

用于是否可查看某一类数据：

- `student:read`
- `apply:view`
- `review:pending`

注意：这类权限只表示“能不能看”，不自动表示“能看所有数据”。

---

## 6. 白名单规范

### 6.1 公开接口白名单

公开接口是无需登录即可访问的接口。

建议包含：

- `/api/auth/login`
- `/api/auth/register`
- `/api/auth/captcha`
- `/health`
- `/docs`
- `/openapi.json`

### 6.2 系统账号白名单

系统账号是拥有全局权限的特殊账号。

建议使用：

- `user_id` 白名单
- 或 `is_super_admin = true`

不建议长期仅用 `username` 识别。

### 6.3 白名单策略

白名单应满足：

- 数量少
- 场景明确
- 有审计记录
- 可随时收敛

---

## 7. Redis Key 命名规范

### 7.1 用户角色缓存

```text
rbac:user:roles:{user_id}
```

示例：

```text
rbac:user:roles:1001
```

### 7.2 用户权限缓存

```text
rbac:user:perms:{user_id}
```

示例：

```text
rbac:user:perms:1001
```

### 7.3 接口权限缓存

```text
rbac:api:{method}:{normalized_path}
```

示例：

```text
rbac:api:GET:/api/system/role
rbac:api:POST:/api/system/role
```

### 7.4 缓存值建议

- `PUBLIC`
- `UNCONFIGURED`
- `permission_code`

---

## 8. 权限变更后的同步规则

当以下对象变化时，需要同步刷新缓存：

- `Permission`
- `RolePermission`
- `UserRole`

同步动作：

- 删除受影响用户的角色缓存
- 删除受影响用户的权限缓存
- 删除受影响接口的权限缓存
- 如有中间件本地缓存，也同步清理

---

## 9. 推荐的权限码与路由示例

### 9.1 管理端

- `account:view` -> `/api/system/account`
- `account:create` -> `POST /api/system/account`
- `account:assign_role` -> `PUT /api/system/account/{id}/roles`
- `role:read` -> `GET /api/system/role`
- `permission:manage` -> `/api/system/permission/*`

### 9.2 业务端

- `apply:create` -> `POST /api/apply`
- `apply:my` -> `GET /api/apply/my`
- `review:pending` -> `GET /api/review/pending`
- `review:approve` -> `POST /api/review/{id}/approve`

---

## 10. 不推荐的做法

- 不推荐使用模糊而宽泛的权限码，比如 `admin`、`all`、`common`
- 不推荐用原始请求 URL 作为最终权限码
- 不推荐把“未配置权限”直接等同于“公开接口”
- 不推荐让白名单覆盖过多业务接口

---

## 11. 文档结论

这份规范的核心目标是：

- 让接口和权限一一对应
- 让缓存键统一可读
- 让白名单边界清晰
- 让权限更新可控且可追踪

---

## 12. 相关文档

- [RBAC 接口鉴权方案文档](./rbac-middleware-implementation-plan.md)
- [RBAC 架构设计图](./rbac-architecture-diagram.md)
- [RBAC 开发实施清单](./rbac-development-checklist.md)
