# RBAC 重置接口方案

> 本文讲一件事：**怎么通过 `POST /api/system/config/rbac/reset` 硬重置 RBAC 系统数据**。
>
> 语义 = 删除 seed 维护的所有系统角色 + 系统权限码 + 角色权限绑定 → 用 seed 重建。**不考虑增量 / 补齐 / 保留现有**。

---

## 1. 目标

| 现状 | 改造后 |
|------|--------|
| lifespan 启动时自动跑 `init_rbac_data()`（upsert） | lifespan 不再跑 seed，由 `POST /api/system/config/rbac/reset` 触发 |
| 想重置 RBAC 只能 SSH 进容器跑脚本 | 系统配置页面点按钮即可 |
| 重置无审计 | 保留原 audit 能力（依赖后续扩展） |

---

## 2. 接口设计

### 2.1 路由

```
POST /api/system/config/rbac/reset
权限：super_admin（PermissionMiddleware 短路放行）
```

### 2.2 请求 / 响应

```http
POST /api/system/config/rbac/reset
Authorization: Bearer <super_admin_token>
Content-Type: application/json
```

```json
{
  "code": 0,
  "message": "success",
  "data": { "message": "RBAC 已硬重置" }
}
```

### 2.3 在 seed 中注册权限码

在 `PERMISSIONS_DATA` 末尾追加一条：

```python
("rbac:reset", "重置 RBAC 系统", "/api/system/config/rbac/reset", "rbac", "权限管理", 145),
```

在 `ROLE_PERMISSIONS["super_admin"]` 显式绑定（虽然中间件短路，绑定上方便审计）：

```python
ROLE_PERMISSIONS = {
    "super_admin": [
        "rbac:reset",
    ],
    # ... 其他角色不变
}
```

> ⚠️ 中间件识别到用户角色含 `super_admin` 时返回 `permissions=["*"]`，reset 接口会被自动放行。
> 但 seed 里显式绑一份，避免"超级管理员靠短路绕开校验"的隐式行为，便于审计追溯。

---

## 3. 改动清单（3 个文件，零 schema 改动）

| # | 文件 | 类型 | 说明 |
|---|------|------|------|
| 1 | `src/scripts/init_rbac_data.py` | 改 | 加常量 + 拆函数 + `mode` 参数 + 新权限码 |
| 2 | `src/app/routes/system_config.py` | 改 | 末尾追加 1 个接口 |
| 3 | `src/infra/database.py` | 改 | `init_db()` 不再调 seed |

---

## 4. 详细改动

### 4.1 `src/scripts/init_rbac_data.py`

#### 4.1.1 新增常量

紧跟 `PERMISSIONS_DATA` 定义之后：

```python
SYSTEM_PERMISSION_CODES = {code for code, *_ in PERMISSIONS_DATA}
SYSTEM_ROLE_CODES = {r["role_code"] for r in ROLES_DATA}
```

#### 4.1.2 重构 `init_rbac_data` 函数

**原签名**：

```python
async def init_rbac_data():
    ...
```

**新签名**：

```python
async def init_rbac_data(mode: str = "upsert"):
    """mode:
      - upsert（默认）：现有逻辑，兼容 lifespan / CLI
      - reset：删 seed 维护的系统 RBAC 数据 → 重建
    """
    async with AsyncSessionLocal() as db:
        try:
            if mode == "reset":
                await _reset_system_rbac(db)
            else:
                await _upsert_rbac(db)
            await db.commit()
        except Exception:
            await db.rollback()
            raise


async def _upsert_rbac(db):
    """现有 init_rbac_data 函数体搬这里，无改动"""
    # ... 原 266~370 行逻辑 ...


async def _reset_system_rbac(db):
    """硬重置：删 seed 维护的 role + permission + role_permission → 用 seed 重建"""
    from sqlalchemy import or_

    sys_role_ids = (await db.execute(
        select(Role.id).where(Role.role_code.in_(SYSTEM_ROLE_CODES))
    )).scalars().all()

    sys_perm_ids = (await db.execute(
        select(Permission.id).where(Permission.permission_code.in_(SYSTEM_PERMISSION_CODES))
    )).scalars().all()

    if sys_role_ids or sys_perm_ids:
        await db.execute(
            delete(RolePermission).where(
                or_(
                    RolePermission.role_id.in_(sys_role_ids),
                    RolePermission.permission_id.in_(sys_perm_ids),
                )
            )
        )

    if sys_perm_ids:
        await db.execute(delete(Permission).where(Permission.id.in_(sys_perm_ids)))

    if sys_role_ids:
        await db.execute(delete(Role).where(Role.id.in_(sys_role_ids)))

    await db.flush()
    await _upsert_rbac(db)

    print(f"[重置] 删除 {len(sys_role_ids)} 角色 + {len(sys_perm_ids)} 权限码，已重建")
```

**向后兼容**：

| 调用方 | 原行为 | 新行为 |
|--------|--------|--------|
| `main.py:20` `await init_db()` | lifespan 跑 upsert | lifespan 不跑（见 4.3） |
| CLI `python -m src.scripts.init_rbac_data` | upsert | upsert（默认 mode） |
| 新增 `POST /reset` 接口 | — | reset |

---

### 4.2 `src/app/routes/system_config.py`

**末尾追加**：

```python
@router.post("/rbac/reset", summary="硬重置 RBAC 系统数据")
async def reset_rbac(db: AsyncSession = Depends(get_db)):
    """仅 super_admin 可调（permission_middleware 短路放行）。

    破坏性操作：
      - 删除 seed 维护的系统角色（4 个）
      - 删除 seed 维护的系统权限码（所有）
      - 删除相关 role_permission
      - user_role 里引用系统角色的记录被 CASCADE 删除（用户失去该角色）

    副作用：
      - 调用者若仅持有 super_admin 角色，会被踢出 → 系统锁死风险
    """
    from src.scripts.init_rbac_data import init_rbac_data

    await init_rbac_data(mode="reset")
    return R.success_resp({"message": "RBAC 已硬重置"})
```

---

### 4.3 `src/infra/database.py`

**第 68~79 行 `init_db()` 改为**：

```python
async def init_db():
    """启动初始化入口（lifespan 调用）

    职责：DB pool 就绪
    RBAC 种子由 POST /api/system/config/rbac/reset 管理
    """
    logger.info("DB pool ready（RBAC 重置请调用 /api/system/config/rbac/reset）")
```

---

## 5. 删除顺序

```
1. DELETE role_permission     ← 先删依赖表（FK 双向被引用）
2. DELETE permission         ← 再删 permission（FK 来源已断）
3. DELETE role               ← 最后删 role（user_role CASCADE 自动清）
```

外键状态已确认：

| FK | 删除策略 | 位置 |
|----|---------|------|
| `user_role.role_id → role.id` | `ON DELETE CASCADE` | `user.py:21` |
| `role_permission.role_id → role.id` | `ON DELETE CASCADE` | `user.py:28` |
| `role_permission.permission_id → permission.id` | `ON DELETE CASCADE` | `user.py:30` |

✅ 整个 reset 流程包在一个 transaction 里，**任何步骤失败全部回滚**。

---

## 6. 首次部署后的操作流程

> 本节基于 **alembic 时代** 的部署步骤写。当前 idbackend **已不用 alembic**（详见 `docs/base/db-schema-sync.md`），
> schema 同步由启动时的 `Base.metadata.create_all()` 自动完成。下列步骤的语义等价，对应如下：

| 历史（alembic 时代） | 现在（create_all 时代） |
|---------------------|------------------------|
| `1. alembic upgrade head` 建 22 张表 | ~~自动同步~~ 启动 backend 时由 `python -m src.main` 自动建表（幂等，详见 db-schema-sync.md 第 2 节） |
| `2. 启动应用` | `2. 启动 backend 容器`（启动时已自动建表，无需手动 db schema 步骤） |
| `3. 手动创建 1 个 super_admin 用户` | `3. 手动创建 1 个 super_admin 用户` ← 同左 |
| `4. 用 super_admin 登录` | `4. 用 super_admin 登录` ← 同左 |
| `5. 调一次 POST /api/system/config/rbac/reset` ← 初始化 RBAC | `5. 调一次 POST /api/system/config/rbac/reset` ← 同左 |
| `6. 之后正常使用` | `6. 之后正常使用` ← 同左 |

**CI/CD 替代方案**（自动初始化）：

```bash
# 1. schema 同步（create_all 已经在 python -m src.main 启动时自动完成，无需手动命令）
# 2. RBAC seed（手动跑一次 init_rbac_data）
python -c "import asyncio; from src.scripts.init_rbac_data import init_rbac_data; asyncio.run(init_rbac_data())"
```

---

## 7. 风险清单

| 风险 | 等级 | 说明 | 防御 |
|------|------|------|------|
| **super_admin 锁死** | 🔴 高 | 调用者若仅持 super_admin，重置后被踢，无法再次调 reset | 建议在 reset 完成后自动给 caller 重新绑 super_admin（需从 middleware 拿 user_id，复杂度 +1） |
| **多实例并发 reset** | 🟡 中 | 多 pod 同时调 reset，可能 race | 建议加 Redis 分布式锁（本期可不做） |
| **permission_id 变更** | 🟡 中 | 重建后 permission 表的 id 重新生成 | JWT 用 permission_code 不用 id，无影响（待确认） |
| **业务角色被误删** | 🟢 低 | `SYSTEM_ROLE_CODES` 只含 4 个系统角色 code，业务角色 code 不在其中 | 安全 ✅ |
| **事务原子性** | 🟢 低 | reset 包在一个 transaction 里，失败回滚 | 安全 ✅ |

---

## 8. 回滚方案

1. **代码回滚**：`git revert` 三个改动
2. **数据回滚**：因为 seed 是删了重建，DB 里的 system 资源就是 seed 内容，跟 git HEAD 一致
3. **极端情况**：seed 脚本本身有 bug → 用户角色权限全丢 → 需要从备份恢复 DB（因为 schema 现在只有 create_all，没有 version 表，无法以"非破坏性"方式回滚 RBAC 数据）

---

## 9. 不在本期范围

- ❌ 前端"重置 RBAC"按钮 + 二次确认 UI（前端同事做）
- ❌ super_admin 锁死防御（建议下期加）
- ❌ Redis 分布式锁（多实例才有）
- ❌ 审计日志（谁/何时点了 reset）
- ❌ E2E 测试用例

---

## 10. 待确认事项

- [ ] **Q1**：是否需要加 super_admin 锁死防御？（推荐加，代码量 +15 行）
- [ ] **Q2**：是否需要加 Redis 分布式锁？（多实例部署才有，本期可不做）
- [ ] **Q3**：JWT 里是否包含 `permission_id`？（一般不包含，请确认）
- [ ] **Q4**：前端是否要加二次确认弹窗？（强烈建议）
- [ ] **Q5**：是否需要审计日志？（写 `system_config` 表或日志文件）
- [ ] **Q6**：lifespan 真的不跑 seed 吗？（替代方案：lifespan 改成"如果 DB 里没有 super_admin 就 seed"）

---

## 11. 评审 checklist

- [ ] 接口路径 `/api/system/config/rbac/reset` 是否合理？
- [ ] 删除策略用 `code IN (seed 常量集合)` 而不是 `is_system` 字段，是否接受？
- [ ] `init_rbac_data(mode="upsert")` 默认值，保证向后兼容，可以吗？
- [ ] 首次部署流程（手动建 super_admin + 调一次 reset），是否符合运维习惯？
- [ ] 是否接受当前 5 项风险等级？