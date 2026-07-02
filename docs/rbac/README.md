# RBAC 权限功能文档

> 本目录包含 RBAC 权限功能的实现方案文档

## 文档列表

| 文档 | 说明 |
|------|------|
| [permission-optimization-v2.md](./permission-optimization-v2.md) | **推荐** - 基于白名单 + 动态中间件的权限优化方案 |
| [implementation-plan.md](./implementation-plan.md) | 完整实现方案（历史版本） |

## 快速导航

### 核心内容
- [动态权限校验（推荐方案）](./permission-optimization-v2.md#四动态权限校验推荐方案) - 中间件自动校验，管理端配置
- [ContextVar 用户上下文](./permission-optimization-v2.md#51-contextvar-用户上下文) - Python 版 ThreadLocal
- [核心流程](./permission-optimization-v2.md#七核心流程) - 请求处理流程图
- [实现清单](./permission-optimization-v2.md#十一实现清单) - 需要修改的文件列表

### 相关工程

| 工程 | 说明 |
|------|------|
| `idpython` | 新工程 (FastAPI) - 需要完善 RBAC |
| `idbackend` | 旧工程 (Java) - 参考实现 |
| `idfrontend-admin` | 前端工程 - 需要对接 |

---

## 核心设计

### 白名单 + 动态中间件

#### 设计思路（类比 Java）

| Java 实现 | Python 实现 | 说明 |
|-----------|------------|------|
| `ThreadLocal` | `ContextVar` | 存储当前请求用户上下文（异步安全） |
| `Interceptor` | `Middleware` | 拦截请求，解析 Token，设置上下文 |
| `@RequiresPermissions` | 数据库配置 | 声明接口需要的权限 |
| 注解 + 反射 | 中间件 + 查表 | 自动校验权限 |

#### 核心组件

```
请求 → AuthMiddleware → 从 JWT 解析用户 → ContextVar.set(user)
                         ↓
                   PermissionMiddleware → 从 interface_permissions 查需要的权限
                         ↓
                   ContextVar.get() 获取用户权限
                         ↓
                   比较：有权限放行 / 无权限 403
```

#### 优势

| 特性 | 说明 |
|------|------|
| **无需代码声明** | 接口不需要写 `Depends(require_permission(...))` |
| **管理端配置** | 权限在数据库中配置，可动态修改 |
| **即时生效** | 修改权限配置后立即生效（可加缓存） |
| **代码整洁** | 业务代码专注于业务逻辑 |

---

## 待完成任务

- [ ] Phase 1: 创建 interface_permissions 表
- [ ] Phase 2: 创建 context.py (ContextVar)
- [ ] Phase 3: 创建 AuthMiddleware
- [ ] Phase 4: 创建 PermissionMiddleware
- [ ] Phase 5: 注册中间件
- [ ] Phase 6: 管理端 API

---

*文档版本: v2.1 | 更新日期: 2026-07-02*
