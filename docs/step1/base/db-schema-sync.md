# DB Schema 同步设计（idbackend）

> **适用版本**：idbackend 当前版本及以后（2026-07-11 起）
> **核心策略**：**不使用 alembic**，所有 model 由 SQLAlchemy 的
> `Base.metadata.create_all()` 在进程启动时自动同步到 DB。

---

## 1. 原则

| 项 | 决策 |
|----|------|
| Schema 同步方式 | `Base.metadata.create_all(engine)` |
| 同步时机 | 容器启动时（`src.main()` 起 uvicorn 之前） |
| 版本表 | **没有**。`alembic_version` 表从概念上删掉 |
| Migration 文件 | **没有**。所有 schema 变更 = 改 `src/models/*.py` + 重新部署 |
| 数据迁移 | 不在 create_all 范围内，复杂数据变更手工 SQL（一次性） |

**为什么不用 alembic**：
- 本项目 model 演进简单（init 后偶尔加字段），迁移脚本手维护成本高于收益
- `Base.metadata.create_all` 完全幂等，对"半清空"残留库容错强
- 部署心智负担 0 —— 「改 model → 重部署 → DB 同步」，一句话讲完
- 不依赖同步/异步 driver 的版本兼容（alembic 的历史包袱）

**create_all 的边界**：
- ✅ 新加表 → 自动创建
- ✅ 新加列 → 自动创建
- ❌ 列类型变更 → **不会**自动改（需要手工 SQL）
- ❌ 删列 → **不会**自动删（需要手工 SQL）
- ❌ 改默认 / 改约束 → **不会**自动改（需要手工 SQL）

本项目接受这个边界 —— 已知/接受的限制已在第 5 节列应急方案。

---

## 2. 启动流程

```
python -m src.main
   │
   ├─ 1. 同步 schema（_sync_schema_blocking）
   │   ├─ import src.models  ← 触发 src/models/__init__.py
   │   │   所有 model 注册到 Base.metadata
   │   └─ Base.metadata.create_all(sync_engine)
   │       ├─ 表不在 → CREATE TABLE
   │       └─ 表已存在 → SKIP（不动）
   │
   └─ 2. 起 uvicorn serve（lifespan 跑 storage init）
```

在 Docker 中：
```dockerfile
CMD ["python", "-m", "src.main"]
```

---

## 3. 加新表 / 加新字段的流程

**例：加一张 `audit_log` 表**

```python
# src/models/audit_log.py
from sqlalchemy import String, Text, Integer
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, TimestampMixin

class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_log"
    actor_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action:   Mapped[str] = mapped_column(String(64), nullable=False)
    detail:   Mapped[str] = mapped_column(Text, nullable=True)
```

```python
# src/models/__init__.py 末尾追加导出
from src.models.audit_log import AuditLog

__all__ = [..., "AuditLog"]
```

**部署**：
```bash
git push                       # 触发 CI 重新构建镜像
# 或者本地：
docker compose pull idbackend
docker compose up -d idbackend
```

启动时 `Base.metadata.create_all` 检测到 `audit_log` 不存在 → 自动 CREATE。

**不需要做的事**：
- ❌ 写 SQL migration 文件
- ❌ 在 server 上手动跑脚本
- ❌ 操作 `alembic_version` 表

---

## 4. 改字段类型 / 删列（需要手工 SQL）

`create_all` 不会改已存在的字段。需要时手工 SQL（**一次性**，提交一份 `docs/migrations/manual-YYYY-MM-DD.md` 记录）：

```sql
-- 例：把 user.phone 从 VARCHAR(20) 改成 VARCHAR(32)
ALTER TABLE users ALTER COLUMN phone TYPE VARCHAR(32);
```

执行方式：
```bash
docker exec -it postgres psql "postgresql://zhouch:zhouchenhui@<宿主机IP>:5432/iddata" \
  -c "ALTER TABLE users ALTER COLUMN phone TYPE VARCHAR(32);"
```

同时改 `src/models/user.py` 的 `String(20)` → `String(32)` 并部署。

---

## 5. 应急：清库重建

如果 DB 状态完全错乱（残留表、缺失主键、半截 init 等），最稳的修复是清卷重建：

```bash
cd /home/project
# 1. 停 backend
docker stop idbackend

# 2. 清 postgres 卷（**会丢所有数据**！）
docker compose down -v

# 3. 重建
docker compose up -d

# 4. 启动后端：自动 create_all 22 张表
docker start idbackend
```

**手动 seed**：lifespan 不再自动跑 RBAC 种子。
- 首次部署：SSH 进 idbackend 跑 `python -m src.scripts.init_rbac_data`
- 后续重置：通过管理端 `POST /api/system/config/rbac/reset` 按钮

---

## 6. 与历史 alembic 的关系

**历史**：2026-07-11 之前，本项目曾短暂使用 alembic 做 schema 同步。
因为「半清空库 + alembic_version 不匹配」反复踩坑，已彻底改为本方案。

**影响范围**：
- 删除了 `alembic/` 目录、`alembic.ini`、相关 `requirements.txt` 依赖
- `Dockerfile` CMD：`alembic upgrade head && exec uvicorn ...` → `python -m src.main`
- `alembic_version` 表残留：如果线上 DB 还有这张表，**无害**（create_all 不碰）
  - 想干净一点：`DROP TABLE IF EXISTS alembic_version;`

**回归 alembic 的门槛**：未来如果 schema diff 复杂度上升（频繁改类型、删列、加 FK 关系），再考虑引入 alembic 或同类型工具。本方案不堵这条路。

---

## 7. FAQ

### Q1. create_all 启动很慢吗？

**不会**。空库 22 张表 DDL 大约 100ms。有数据但表已存在 → 0 SQL。

### Q2. 想本地不自动同步 schema（开发时反复触发）？

可以绕过 `python -m src.main`，直接 `uvicorn main:app --reload` 启动：
- 不会触发 schema 同步
- 但**只对当前 DB 已存在表**有效；新增 model 必须跑一次 `python -m src.main`

### Q3. 多副本部署（多容器）时 create_all 会冲突吗？

**不会**。PostgreSQL 对 CREATE TABLE IF NOT EXISTS 行为幂等（DQL 一定）。
SQLAlchemy 的 create_all 内部用 IF NOT EXISTS，等价安全。

### Q4. 加新表时如何确认被 create_all 抓到？

```bash
# 启动 backend 后，看日志第一行：
docker logs idbackend 2>&1 | head -3
# 应输出：
# [idpython] schema synced via Base.metadata.create_all (NN tables)
```

`NN` 比上次 +1 即代表新表被同步了。

### Q5. 删一个 model 文件会删 DB 表吗？

**不会**。create_all 永远不 DROP TABLE。要删表手工 SQL：
```sql
DROP TABLE IF EXISTS obsolete_table CASCADE;
```

