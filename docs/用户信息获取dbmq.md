# 用户权限信息获取方案：DB + ContextVar 演进路线

> 适用范围：`PermissionMiddleware` 鉴权链路中"用户信息/角色/权限集合"与"path → permission_code 映射"的获取方式。
> 编写目的：把当前"Redis 30min TTL 缓存"带来的不一致窗口问题彻底梳理清楚，并给出一套**演进路径**。
> 当前状态：计划阶段，代码尚未修改。

---

## 一、问题回顾

当前 `PermissionMiddleware` 用 Redis 缓存用户权限集合（TTL 30 分钟）和 api_path → permission_code 映射（TTL 5 分钟）。当 DB 中权限发生变更后：

```
管理端改 permission（DB 真源）
   ↓
Redis 中还是旧值
   ↓
最多 30 分钟内，中间件继续用旧权限判断
   ↓
线上出现：用户该有的权限拿不到 / 用户已撤销的权限仍能用
```

此外还有**多 worker 部署不一致**问题——即使加了写时失效，业务代码漏掉一处 `invalidate()` 就有 bug。

同时，当前 `context.py` 中的 `ContextVar` 仅存 `user_id / username` 两个字段，业务代码中鉴权用的角色/权限列表无法直接获取，需要在 `deps.py` 中重复查 DB（`get_current_user`），或各自散落在业务代码里多次查询。

---

## 二、缓存的本质：DB 是真源，缓存是副本

| 缓存方式 | 和 DB 不同步的场景 | 不一致窗口 |
|---|---|---|
| Redis + TTL 30 分钟 | DB 改了，Redis 还是旧的 | 30 分钟内 |
| 进程内 dict + TTL 60s | DB 改了，dict 还是旧的 | 60 秒内 |
| JWT token 里塞权限 | DB 改了，token 还是旧的 | token 过期前（可能 24h+） |
| 无缓存（每次查 DB） | —— | **0（永远一致）** |

三者问题**本质相同**：写 DB 后没强制让读侧失效。

---

## 三、第一阶段：每次查 DB，结果写入 ContextVar（无缓存）

### 设计目标

在 `PermissionMiddleware` 的鉴权链路中，一次 DB 查询拉取**完整用户信息**（身份 + 角色 + 权限码），存入 `ContextVar`。后续所有业务代码和 `deps.py` 的 `get_current_user` 直接从 `ContextVar` 取用，**不再重复查 DB**。

### 架构图

```
请求进入
    ↓
AuthMiddleware（解析 JWT，设置 user_id/username 到 ContextVar）
    ↓
PermissionMiddleware
    ↓
一次 DB 查询（用户表 + 角色表 + 权限表 JOIN）
    ↓
将 {user_id, username, roles, permissions} 整体写入 ContextVar
    ↓
业务代码 / deps.get_current_user() 直接从 ContextVar 读取
    ↓
无 MQ，无 Redis 缓存，一致性为 0 窗口
```

### ContextVar 存储结构

```python
# src/app/context.py

_current_user: ContextVar[Optional[dict]] = ContextVar('current_user', default=None)

# 存储结构（示例）：
{
    "user_id": 123,
    "username": "admin",
    "is_admin": False,            # 是否系统白名单用户
    "roles": [                    # 角色列表（用于业务展示）
        {"role_id": 1, "role_name": "审核员"},
        {"role_id": 2, "role_name": "数据分析师"},
    ],
    "permissions": [              # 权限码列表（用于鉴权）
        "system:user:list",
        "system:user:create",
        "audit:record:view",
        "*",
    ],
}
```

### 一次 DB 查询 SQL

```sql
SELECT
    u.id          AS user_id,
    u.username,
    u.status      AS user_status,
    p.permission_code,
    r.id          AS role_id,
    r.name        AS role_name
FROM users u
LEFT JOIN user_role  ur  ON ur.user_id  = u.id
LEFT JOIN role       r   ON r.id        = ur.role_id
LEFT JOIN role_permission rp ON rp.role_id = r.id
LEFT JOIN permission p    ON p.id       = rp.permission_id
WHERE u.id = $1
  AND u.status = true
  AND (r.status = true  OR r.status IS NULL)
  AND (p.status = true   OR p.permission_code IS NULL);
```

### 字段说明

| 字段 | 来源表 | 说明 |
|---|---|---|
| `user_id` | users | 用户 ID |
| `username` | users | 用户名 |
| `user_status` | users | 用户状态（用于判断账号是否被禁用） |
| `role_id` | role | 用户持有的角色 ID |
| `role_name` | role | 用户持有的角色名称（展示用） |
| `permission_code` | permission | 用户持有的权限码（鉴权用） |

### deps.py 改造

```python
# src/app/deps.py

@dataclass
class CurrentUser:
    """当前登录用户（所有字段均从 ContextVar 直接获取，不再查 DB）"""
    user_id: int
    username: str
    is_admin: bool
    roles: List[dict]      # [{"role_id": 1, "role_name": "xxx"}, ...]
    permissions: List[str] # ["system:user:list", ...]


def get_current_user() -> CurrentUser:
    """直接从 ContextVar 读取完整用户信息，无 DB 调用"""
    from src.app.context import get_current_user_full
    ctx = get_current_user_full()
    if ctx is None:
        raise HTTPException(status_code=401, detail="请先登录")
    return CurrentUser(
        user_id=ctx["user_id"],
        username=ctx["username"],
        is_admin=ctx["is_admin"],
        roles=ctx["roles"],
        permissions=ctx["permissions"],
    )
```

### ContextVar 辅助函数

```python
# src/app/context.py 新增

def set_current_user_full(user: Optional[Dict[str, Any]]) -> None:
    """设置完整用户信息到请求上下文（PermissionMiddleware 调用）"""
    _current_user.set(user)


def get_current_user_full() -> Optional[Dict[str, Any]]:
    """获取完整用户信息"""
    return _current_user.get()


def get_user_permissions() -> List[str]:
    """获取当前用户权限码列表"""
    user = get_current_user_full()
    return user.get("permissions", []) if user else []


def get_user_roles() -> List[dict]:
    """获取当前用户角色列表"""
    user = get_current_user_full()
    return user.get("roles", []) if user else []


def has_permission(code: str) -> bool:
    """检查当前用户是否持有指定权限码"""
    perms = get_user_permissions()
    return "*" in perms or code in perms
```

### 为什么性能 OK

- QPS：管理后台 + 审核系统，峰值估算 ≤ 100
- 单次 JOIN 查询耗时：2~5 ms（局域网 PG）
- 100 QPS × 5ms = 500ms/s 单核，**完全不是瓶颈**
- 同一请求内，业务代码多次调用 `get_current_user()` 无额外 DB 开销

### 一致性保证

- DB 是唯一真源，鉴权链路每次读必查 DB
- 改完权限 → 下一次请求立即看到新值
- **零不一致窗口**

### 监控点

上线后建议观察：

```sql
-- pg_stat_statements 看用户信息 JOIN 查询的调用次数和平均耗时
SELECT query, calls, mean_exec_time
FROM pg_stat_statements
WHERE query ILIKE '%user_role%role%permission%'
ORDER BY calls DESC
LIMIT 10;
```

如果平均耗时 < 10ms 且 DB CPU < 30%，说明方案无压力，可以长期使用。

---

## 四、第二阶段：引入 MQ 做缓存失效广播（QPS 上来后）

### 触发条件

满足以下任一条件，进入第二阶段：

- 单实例 QPS > 200
- DB CPU > 40%（仅 RBAC 相关查询就占了 30%+）
- 多 worker / 多机部署，且**业务代码维护方表示管理端写时失效容易漏**

### 架构图

```
        ┌──────────────┐  1.update  ┌──────────────┐
        │  管理端 Web   │ ─────────→ │     DB       │
        └──────┬───────┘             └──────────────┘
               │ 2.publish
               ↓
        ┌──────────────┐
        │  MQ Broker   │  (Redis Pub/Sub 或 RabbitMQ / Kafka)
        └──────┬───────┘
               │ 3.subscribe
   ┌───────────┼───────────┐
   ↓           ↓           ↓
Worker A    Worker B    Worker C
(本地 LRU)  (本地 LRU)  (本地 LRU)
   ↓           ↓           ↓
Redis L2 缓存（可选，作为 L1 miss 后的二级缓存）
   ↓
DB
```

### 三层缓存层次

| 层级 | 内容 | 共享范围 | 失效方式 |
|---|---|---|---|
| L1 | 进程内 dict（`cachetools.LRUCache`） | 单 worker | MQ 事件触发 `pop` |
| L2 | Redis（短 TTL，如 60s） | 跨 worker | MQ 事件触发 `delete` |
| L3 | DB | 真源 | —— |

请求路径：`L1 → L2 → DB`，L1/L2 都不命中再查 DB。
第一阶段存入 ContextVar 的逻辑保持不变，只是"L3 → DB"的查询多了 L1/L2 两层缓存。

### MQ 事件协议

**Topic**：`rbac:perm:invalidate`

**Payload**（JSON）：

```json
{
  "event_type": "permission_changed",
  "scope": "user",
  "user_id": 123,
  "operator_id": 1,
  "timestamp": "2026-07-03T13:00:00+08:00"
}
```

**事件类型枚举**：

| event_type | scope | payload 字段 | 失效动作 |
|---|---|---|---|
| `permission_changed` | `user` | `user_id` | L1.pop(user_id), L2.del(`rbac:user:perms:<user_id>`) |
| `permission_changed` | `role` | `role_id` | L1.pop(所有持该 role 的 user), L2.del(对应 user 的 key) |
| `permission_changed` | `path` | `api_path` | L1.pop(api_path), L2.del(`rbac:api:perm:<path>`) |
| `permission_reset` | `all` | —— | L1.clear(), L2.flush_by_prefix(`rbac:`) |

### 管理端写操作改造

原本（每个管理端写路由都要记得调 `invalidate_*`）：

```python
# 容易漏 ❌
@router.post("/permission/update")
async def update_permission(...):
    await db.execute(...)
    await invalidate_path_in_redis(path)   # 漏掉就出 bug
    await invalidate_user_in_redis(user_id) # 漏掉就出 bug
    return {"ok": True}
```

改成统一事件发布：

```python
# 统一入口，强制不会漏 ✅
@router.post("/permission/update")
async def update_permission(...):
    await db.execute(...)
    await mq.publish("rbac:perm:invalidate", {
        "event_type": "permission_changed",
        "scope": "path",
        "api_path": path,
    })
    return {"ok": True}
```

`mq.publish()` 实现为**同步双写**：先写 DB，commit 成功后再 `redis.publish()`。失败重试一次。

### Worker 订阅实现

每个 Web 进程启动时订阅：

```python
# src/app/middleware/perm_cache_subscriber.py
async def start_perm_cache_subscriber():
    redis = await get_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe("rbac:perm:invalidate")
    async for msg in pubsub.listen():
        if msg["type"] != "message":
            continue
        payload = json.loads(msg["data"])
        await handle_invalidate_event(payload)

async def handle_invalidate_event(payload: dict):
    scope = payload.get("scope")
    if scope == "user":
        local_cache.pop(payload["user_id"], None)
        await redis.delete(f"rbac:user:perms:{payload['user_id']}")
    elif scope == "path":
        api_cache.pop(payload["api_path"], None)
        await redis.delete(f"rbac:api:perm:{payload['api_path']}")
    elif scope == "role":
        # 查 role_id → 所有 user_id → 全清
        user_ids = await db_get_users_by_role(payload["role_id"])
        for uid in user_ids:
            local_cache.pop(uid, None)
            await redis.delete(f"rbac:user:perms:{uid}")
    elif scope == "all":
        local_cache.clear()
        await redis.flush_by_prefix("rbac:")
```

### 一致性保证

- 写 DB → publish 事件之间的时间窗口（通常 < 1ms）内，可能有读到旧缓存的请求
- 但**不会再有"30 分钟"的滞后窗口**
- 最坏情况：用户感知到新权限的延迟 = 1~2 个 RTT（网络 + MQ 投递）

---

## 五、第三阶段（可选）：多机部署的兜底

如果未来部署到多台机器（k8s 多 pod），上面 Redis Pub/Sub 已经天然适配多机。升级路径：

| 部署规模 | MQ 选型 |
|---|---|
| 单机房 4-8 worker | Redis Pub/Sub（已经够用） |
| 多机房 / 大流量 | RabbitMQ 或 Kafka（更可靠投递） |

切换 MQ 时只换 `mq.publish()` 和 `mq.subscribe()` 的实现，事件协议不变。

---

## 六、改动文件清单

### 第一阶段（每次查 DB + ContextVar）

| 文件 | 改动 |
|---|---|
| `src/app/context.py` | 新增 `set_current_user_full()`、`get_current_user_full()`、`get_user_permissions()`、`get_user_roles()`、`has_permission()` 辅助函数 |
| `src/app/middleware/permission_middleware.py` | 移除 Redis 缓存；`get_user_permissions()` 改为单次 JOIN 查询，查询完整用户信息并调用 `set_current_user_full()` 写入 ContextVar；删除 `_USER_PERM_TTL`、`_API_PERM_TTL` 常量 |
| `src/app/deps.py` | `get_current_user()` 改为从 ContextVar 读取完整用户信息，不再查 DB；扩展 `CurrentUser` dataclass 增加 `is_admin`、`roles`、`permissions` 字段 |
| `src/app/middleware/auth_middleware.py` | **无需改动**（仍只设置 `user_id/username`，完整信息由 PermissionMiddleware 补充） |
| 业务路由 | **零改动**（直接受益：所有 `Depends(get_current_user)` 现在自带 roles/permissions） |

### 第二阶段（引入 MQ 广播失效）

| 文件 | 改动 |
|---|---|
| `src/app/middleware/permission_middleware.py` | 改回缓存逻辑，走 L1+L2 双层 |
| `src/app/middleware/perm_cache_subscriber.py`（新增） | 订阅 MQ 失效事件 |
| 管理端写路由（约 4 处） | 写 DB 后改用 `mq.publish()` 统一事件 |

---

## 七、不推荐的方案

### ❌ JWT 里塞用户权限

- token 24h+ 不一致窗口
- 用户改完密码/权限后必须强制下线
- 复杂度极高（refresh token + 黑名单）

### ❌ lru_cache 装饰器

- 无法主动失效，要等 LRU 驱逐
- 多 worker 时不一致窗口无限

### ❌ 只靠 Redis TTL（当前方案）

- 30 分钟不一致窗口过大
- 改完权限用户体验差
- 写时失效机制靠人维护容易漏

---

## 八、落地 checklist

### 第一阶段上线前

- [ ] 确认 `PermissionMiddleware` 改造后的 JOIN SQL 覆盖所有必要字段
- [ ] `context.py` 新增 `get_current_user_full()` 等辅助函数
- [ ] `deps.py` 的 `get_current_user()` 切换为从 ContextVar 读取
- [ ] 回归测试 10+ 接口（重点：鉴权链路、业务代码中 `Depends(get_current_user)` 的各路由）
- [ ] 观察 DB 慢日志，确认 JOIN 查询耗时 < 10ms
- [ ] 确认管理端改权限后前端刷新立即看到新菜单/新权限

### 第一阶段上线后

- [ ] 持续观察 1 周 DB QPS 和 CPU
- [ ] 收集"权限相关"的 SQL 调用次数
- [ ] 如果都正常，方案定稿不再加缓存

### 触发第二阶段的指标

- [ ] DB QPS > 200 且权限相关查询占比 > 30%
- [ ] 或多 worker 部署且业务方反馈"改权限容易漏失效"

---

## 九、参考

- 当前代码：`src/app/middleware/permission_middleware.py`
- ContextVar：`src/app/context.py`
- 依赖注入：`src/app/deps.py`
- RBAC 业务逻辑：`src/services/rbac_service.py`
- 权限管理路由：`src/app/routes/permission.py`（如有）
- 重置脚本：`scripts/fix_permissions_full.py`
