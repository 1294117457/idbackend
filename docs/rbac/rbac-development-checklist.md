# RBAC 开发实施清单

> 目标：把 RBAC 接口鉴权方案拆成可执行的开发任务，按优先级推进实现。

---

## 1. 开发目标

### 1.1 必须实现

- [ ] 用户、角色、权限、关联表模型可用
- [ ] `permission` 绑定后端接口
- [ ] `role` 绑定 `permission`
- [ ] `user` 绑定 `role`
- [ ] `AuthMiddleware` 可解析登录态
- [ ] `PermissionMiddleware` 可完成接口鉴权
- [ ] Redis 可缓存接口权限映射
- [ ] 权限变更可刷新缓存
- [ ] 白名单可放行公开接口和系统账号

### 1.2 建议补充

- [ ] 接口扫描工具
- [ ] 权限码命名规范
- [ ] 前端菜单权限联动
- [ ] 按钮级权限控制
- [ ] 审计日志

---

## 2. 任务分解

### Phase 1：数据结构确认

- [ ] 确认 `User / Role / Permission / UserRole / RolePermission` 模型字段
- [ ] 明确 `permission` 与接口映射字段
- [ ] 明确是否支持一个权限绑定多个接口
- [ ] 补充唯一约束与索引

### Phase 2：权限码规范

- [ ] 统一权限码格式
- [ ] 定义资源名与动作名
- [ ] 定义菜单权限与接口权限的关系
- [ ] 定义公开接口与受控接口的分类

### Phase 3：Redis 缓存设计

- [ ] 设计接口权限缓存 key
- [ ] 设计用户角色缓存 key
- [ ] 设计用户权限缓存 key
- [ ] 定义缓存状态：`PUBLIC` / `AUTH_REQUIRED` / `UNCONFIGURED`
- [ ] 明确缓存过期和主动失效策略

### Phase 4：认证中间件

- [ ] 编写 `AuthMiddleware`
- [ ] 完成公开接口白名单
- [ ] 完成 JWT 解析
- [ ] 将用户信息写入请求上下文
- [ ] 实现系统白名单账号识别

### Phase 5：权限中间件

- [ ] 编写 `PermissionMiddleware`
- [ ] 读取当前请求 method 与 normalized path
- [ ] 优先查 Redis
- [ ] Redis miss 时查数据库
- [ ] 根据用户权限判断放行或拒绝
- [ ] 统一返回 401 / 403 响应

### Phase 6：权限管理功能

- [ ] 权限新增/编辑/删除
- [ ] 角色新增/编辑/删除
- [ ] 角色分配权限
- [ ] 用户分配角色
- [ ] 操作后刷新缓存

### Phase 7：接口扫描与维护

- [ ] 提供接口扫描建议
- [ ] 提供权限码自动生成规则
- [ ] 提供未配置接口的检查功能
- [ ] 提供权限配置列表导出

### Phase 8：前端联动

- [ ] 登录后获取用户角色/权限
- [ ] 路由守卫接入权限判断
- [ ] 菜单按权限过滤
- [ ] 按钮按权限显示/隐藏
- [ ] 无权限时展示统一提示

---

## 3. 开发顺序建议

### 第一阶段：先跑通鉴权主链路

1. 认证中间件
2. 权限中间件
3. Redis 缓存
4. 接口权限映射
5. 白名单

### 第二阶段：完善 RBAC 关系

1. 角色管理
2. 权限管理
3. 用户角色分配
4. 角色权限分配

### 第三阶段：提升可维护性

1. 接口扫描
2. 权限码规范化
3. 前端权限联动
4. 日志与审计

---

## 4. 文件层面实施清单

### 4.1 后端建议新增

- [ ] `src/app/context.py`
- [ ] `src/app/middleware/auth_middleware.py`
- [ ] `src/app/middleware/permission_middleware.py`
- [ ] `src/app/middleware/__init__.py`
- [ ] `src/app/utils/path_normalizer.py`

### 4.2 后端建议修改

- [ ] `src/infra/jwt.py`
- [ ] `src/services/rbac_service.py`
- [ ] `src/services/auth_service.py`
- [ ] `src/main.py`
- [ ] `src/app/routes/permission.py`
- [ ] `src/app/deps.py`

### 4.3 前端建议修改

- [ ] 登录态存储
- [ ] 路由守卫
- [ ] 菜单生成逻辑
- [ ] 按钮权限指令或组件

---

## 5. 权限更新时必须做的事

每次以下对象变更时都要处理缓存：

- [ ] 新增 permission
- [ ] 更新 permission
- [ ] 删除 permission
- [ ] 更新 role_permission
- [ ] 更新 user_role

对应动作：

- [ ] 清用户角色缓存
- [ ] 清用户权限缓存
- [ ] 清接口权限映射缓存
- [ ] 必要时刷新中间件内存缓存

---

## 6. 验收标准

### 6.1 功能验收

- [ ] 普通用户不能访问管理员接口
- [ ] 审核员只能访问审核相关接口
- [ ] 超级管理员可访问全部接口
- [ ] 公开接口无需登录可访问
- [ ] 未配置权限的接口能被识别并处理

### 6.2 性能验收

- [ ] 常规请求优先命中 Redis
- [ ] Redis miss 可回源数据库
- [ ] 权限变更后生效时间可控

### 6.3 安全验收

- [ ] 没有权限时返回 403
- [ ] 没有登录时返回 401
- [ ] 白名单只覆盖必要场景
- [ ] 不存在过度放行

---

## 7. 推荐里程碑

### M1

- 完成中间件 + Redis + 白名单

### M2

- 完成 RBAC 数据管理与分配

### M3

- 完成前端菜单/按钮权限联动

### M4

- 完成接口扫描、审计、导出

---

## 8. 风险提醒

- 不要默认把“未配置权限”当作“公开接口”
- 不要让白名单范围无限扩大
- 不要用原始 URL 直接做唯一 key
- 不要让权限缓存失效策略只依赖 TTL

---

## 9. 相关文档

- [RBAC 接口鉴权方案文档](./rbac-middleware-implementation-plan.md)
- [RBAC 架构设计图](./rbac-architecture-diagram.md)
- [RBAC 接口与权限码规范](./rbac-interface-and-permission-code-spec.md)
