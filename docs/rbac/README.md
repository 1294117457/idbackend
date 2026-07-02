# RBAC 权限功能文档

> 本目录包含 RBAC 权限功能的实现方案文档

## 文档列表

| 文档 | 说明 |
|------|------|
| [implementation-plan.md](./implementation-plan.md) | 完整实现方案（推荐先阅读） |

## 快速导航

### 核心内容
- [现状分析](./implementation-plan.md#一现状分析) - 现有数据表和代码问题
- [实现方案](./implementation-plan.md#二实现方案) - 技术架构和目录结构
- [详细设计](./implementation-plan.md#三详细设计) - 核心服务、API 设计
- [实现计划](./implementation-plan.md#六实现计划) - 分阶段实施步骤

### 相关工程

| 工程 | 说明 |
|------|------|
| `idpython` | 新工程 (FastAPI) - 需要完善 RBAC |
| `idbackend` | 旧工程 (Java) - 参考实现 |
| `idfrontend-admin` | 前端工程 - 需要对接 |

## 待完成任务

- [ ] Phase 1: 核心 RBAC 服务
- [ ] Phase 2: 后台管理 API
- [ ] Phase 3: 用户角色分配
- [ ] Phase 4: 数据初始化
- [ ] Phase 5: 优化完善

---

## 核心设计

### SuperAdmin 白名单机制

为了实现"超级管理员拥有全部权限"的需求，同时保持代码的隐蔽性和简洁性，采用**用户名白名单**方案。

#### 设计原则

| 原则 | 说明 |
|------|------|
| 隐蔽性 | 不新增数据库字段，不暴露"超级管理员"字样 |
| 简洁性 | 仅在 RBAC 核心服务中加几行判断逻辑 |
| 兼容性 | 不影响现有 RBAC 体系的正常运行 |
| 可控性 | 白名单配置在代码中，可随时修改 |

#### 实现原理

```
┌─────────────────────────────────────────────────────────────┐
│                     RbacService.get_user_permissions()       │
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

#### 白名单配置

在 `src/infra/config.py` 中配置：

```python
# 系统内置账户（看起来像普通配置）
SYSTEM_ACCOUNTS: list = ["admin"]
```

在 `src/services/rbac_service.py` 中实现：

```python
class RbacService:
    """RBAC 核心服务"""
    
    # 从配置读取白名单
    ADMIN_USERS: List[str] = []  # 运行时从 settings 获取
    
    @staticmethod
    async def get_user_permissions(user_id: int) -> List[str]:
        """获取用户权限（含 SuperAdmin 自动扩展）"""
        
        # 1. 查询用户
        user = await db.get(User, user_id)
        if not user:
            return []
        
        # 2. 【关键】检查是否在白名单中
        if user.username in RbacService.ADMIN_USERS:
            return ["*"]  # 返回所有权限
        
        # 3. 普通用户走标准 RBAC
        return await RbacService._query_user_permissions(user_id)
```

#### 使用方式

| 操作 | 步骤 |
|------|------|
| 添加超级管理员 | 在 `SYSTEM_ACCOUNTS` 中添加用户名 |
| 移除超级管理员 | 从 `SYSTEM_ACCOUNTS` 中删除用户名 |
| 生效方式 | 重启服务即可 |

#### 数据库视角

白名单机制**不需要修改数据库**，数据库中完全看不到任何异常：

```sql
-- users 表（看起来完全正常）
SELECT * FROM users;
┌────┬──────────┬─────────────────────┐
│ id │ username │ password            │
├────┼──────────┼─────────────────────┤
│  1 │ admin    │ $2b$12$hashed...    │ ← 看起来就是普通管理员
└────┴──────────┴─────────────────────┘

-- 没有任何 super_admin、is_superuser 等字段
```

#### 前端视角

```json
// admin 用户登录后获取的权限
{
  "userId": 1,
  "username": "admin",
  "permissions": ["*"]  // 表示拥有全部权限
}
```

---

*文档版本: v2.1 | 更新日期: 2026-07-02*
