# Alembic 切换操作清单（idbackend）

> **目的**：用 Alembic 替换手写 SQL migration，建立"改 model → 自动生成 migration → review → 部署"的标准化流程。
>
> **适用范围**：`idbackend`（FastAPI + SQLAlchemy 2.0 + asyncpg）
>
> **前置条件**：当前 DB schema 已与 `src/models/*.py` 完全一致（已通过 `idinfra/iddata-2026-07-11_133038-dump.sql` 核对，20 张表 + 索引 + 约束 + 外键 100% 匹配）。
>
> **策略**：**方案 A**——保留最新 DB 状态，扔掉 `migrations/` 22 个手写文件，alembic 只管"从今天开始"。

---

## 目录

1. [总览](#1-总览)
2. [关键概念澄清](#2-关键概念澄清)
3. [前置准备](#3-前置准备)
4. [切换步骤（按顺序执行）](#4-切换步骤按顺序执行)
5. [生成 migration 后的 review 检查清单](#5-生成-migration-后的-review-检查清单)
6. [部署命令改造](#6-部署命令改造)
7. [日常开发流程（切换完成后）](#7-日常开发流程切换完成后)
8. [常见坑 & 注意事项](#8-常见坑--注意事项)
9. [回滚预案](#9-回滚预案)

---

## 1. 总览

### 1.1 切换前 vs 切换后

```
切换前                                       切换后
─────────────                                ─────────────
src/migrations/                              alembic/
├── 002_xxx.py                               ├── env.py
├── 003_xxx.py                               ├── script.py.mako
├── ... (共 22 个手写 SQL)                   └── versions/
└── clean_user_fields.py                         ├── xxxx_init_base_schema.py
                                                   ├── xxxx_add_user_phone.py
启动时: lifespan 调                              └── ...
  init_db() → CREATE ALL
                                             启动时: lifespan 跑 init_rbac_data()（幂等）
                                             部署时: alembic upgrade head（按当前镜像里的 migration）
```

### 1.2 关键事实

- **Alembic 不是消除 migration 文件**，而是**自动化生成 migration 文件**。生成的 `alembic/versions/*.py` 仍必须 commit 进 git。
- **不需要回填历史**：当前 DB 已是最新状态，我们只是"标记一下"，让 alembic 知道"从今天开始"管 schema。
- **首次切换后**：未来改 model → 跑一条命令 → alembic 自动生成 diff migration → 你 review → commit → 部署时自动跑。
- **schema 跟 git commit 绑定，不是跟 Dockerfile 绑定**：models、`alembic/versions/`、业务代码在同一个 git commit 里 → 自动组成同一个 Docker 镜像 → 部署时镜像里跑 `alembic upgrade head`。Dockerfile 只是"打包脚本"，本身不涉及任何 schema 知识。

---

## 2. 关键概念澄清

| 概念 | 含义 | 切换时的操作 |
|------|------|-------------|
| `alembic revision --autogenerate` | 对比 models 与 DB，生成 diff migration | 首次切换用一次，生成 init_base_schema |
| `alembic stamp head` | 把当前 DB 标记为"已是最新版"，**不真跑** migration | 切换时必做，避免 alembic 想跑 init migration |
| `alembic upgrade head` | 跑所有未执行的 migration（DDL） | 部署时执行 |
| `alembic downgrade -1` | 回滚一个 migration | 紧急回滚时用 |
| `_alembic_version` 表 | alembic 在 DB 里建的版本记录表 | 切完会自动出现，无需手工建 |

---

## 3. 前置准备

### 3.1 确认环境

```bash
# 进入项目根目录
cd /home/dustp/codes/idproject/idbackend

# 确认 Python 环境
python --version       # >= 3.10

# 确认当前 DB 可连通
psql "postgresql://zhouch:zhouchenhui@223.109.49.63:5432/iddata" -c "\dt"
# 应能看到 20 张表
```

### 3.2 备份当前 DB（强烈建议）

```bash
# 已有 dump: idinfra/iddata-2026-07-11_133038-dump.sql
# 切 Alembic 过程中如出问题，至少有一份完整 DB 备份可恢复
```

### 3.3 确认 models 与 DB 一致（已通过）

> 已在 2026-07-11 用 `idinfra/iddata-2026-07-11_133038-dump.sql` 比对过：
> - 20 张表全部匹配
> - 唯一约束、CHECK 约束、外键 ON DELETE 策略全部匹配
> - 索引匹配（DB 存在一处冗余 `ix_applications_user_id`，可忽略）

---

## 4. 切换步骤（按顺序执行）

### 步骤 1：安装 alembic

**文件**：`idbackend/requirements.txt`

```bash
cd /home/dustp/codes/idproject/idbackend
pip install alembic
# 把 alembic==<version> 加到 requirements.txt
```

**验证**：
```bash
alembic --version
# 输出类似：alembic 1.13.x
```

---

### 步骤 2：初始化 alembic 目录

**位置**：项目根目录（与 `src/`、`docs/` 平级）

```bash
cd /home/dustp/codes/idproject/idbackend
alembic init alembic
```

**产物**：
```
idbackend/
├── alembic/
│   ├── env.py                    ← 待修改
│   ├── script.py.mako            ← 不动
│   └── versions/                 ← migration 文件目录（空）
├── alembic.ini                   ← alembic 配置文件
└── ...
```

**注意**：`migrations/`（项目根目录）和 `src/migrations/` 是两回事。前者是历史手写 SQL 目录，后者是 `clean_user_fields.py` 所在位置。**两者都要在切换完成后删除**。

---

### 步骤 3：改 `alembic/env.py`

**目的**：
1. 让 alembic 知道 `Base.metadata` 在哪
2. 让 alembic 能从 `.env` 读 `DATABASE_URL`

**修改点**：

```python
# alembic/env.py
# 在文件顶部加：
import os
from dotenv import load_dotenv
from pathlib import Path

# 项目根 .env
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# 把 sqlalchemy.url 改成读环境变量
config.set_main_option(
    "sqlalchemy.url",
    os.getenv("DATABASE_URL", "postgresql://localhost/dbname")
)

# target_metadata 指向 Base.metadata
from src.models.base import Base
target_metadata = Base.metadata
```

**重要细节**：
- `DATABASE_URL` 是 `postgresql://...`，alembic 用同步 driver（`psycopg2`），不要改成 `postgresql+asyncpg://`
- `env.py` 默认生成的是 async 版本模板，需要确保 `run_migrations_online()` 用的是**同步 engine**（直接用默认即可）
- 如果 `pip install` 时没装 `psycopg2-binary`，需要：`pip install psycopg2-binary`（或者改用 `psycopg`，alembic 1.13+ 支持）

---

### 步骤 4：生成首个 base migration

```bash
cd /home/dustp/codes/idproject/idbackend
alembic revision --autogenerate -m "init_base_schema"
```

**产物**：
```
alembic/versions/
└── xxxx_init_base_schema.py    ← 自动生成
```

**⚠️ 注意**：这时不要立即跑 `alembic upgrade head`，因为 DB 已有这些表，再跑一次会报错。

---

### 步骤 5：**手工 review** 生成的 migration

打开 `alembic/versions/xxxx_init_base_schema.py`，逐项核对：

| 核对项 | 预期 |
|--------|------|
| 包含 20 张表的 `op.create_table()` | ✅ |
| 包含所有 `ForeignKeyConstraint` | ✅ |
| 包含所有 `UniqueConstraint` | ✅ |
| 包含所有 `CheckConstraint`（attribute/rule.type、template.max_score） | ✅ |
| 包含所有 `Index` | ✅（允许少量"已有但不需创建"的差异，详见 5.2） |
| 字段类型、长度、nullable 正确 | ✅ |
| `cascade="all, delete-orphan"` 行为正确 | ✅（外键 ondelete 已经用 CASCADE/SET NULL） |

**如果发现 alembic 漏了某些约束**（autogenerate 不完美）：
- 手动在 migration 里补 `op.create_unique_constraint()`、`op.create_check_constraint()`、`op.create_index()`

**这一步是整个切换的核心，绝不能跳过**。

---

### 步骤 6：stamp head（关键！）

```bash
cd /home/dustp/codes/idproject/idbackend
alembic stamp head
```

**做了什么**：
- 在 DB 里创建 `alembic_version` 表
- 写入当前最新 revision id
- **不执行任何 DDL**

**为什么必须**：当前 DB 已有所有表，不告诉 alembic "已经是最新版"，下次 `alembic upgrade head` 会想再跑一遍 init migration（必报"表已存在"）。

**验证**：
```bash
psql "postgresql://zhouch:zhouchenhui@223.109.49.63:5432/iddata" -c "\d alembic_version"
# 应能看到一行记录：version_num = <head_revision>
```

---

### 步骤 7：删除手写 migration

**删除两处**：

```bash
cd /home/dustp/codes/idproject/idbackend

# 7.1 删除项目根目录的 migrations/（22 个手写 SQL 文件）
rm -rf migrations/

# 7.2 删除 src/migrations/clean_user_fields.py
rm src/migrations/clean_user_fields.py
rmdir src/migrations/ 2>/dev/null || true   # 目录可能还有其他文件，手动检查后删
```

**确认 src/migrations/ 目录内没有其他需要保留的文件后再删**。

---

### 步骤 8：改 `src/infra/database.py` 的 `init_db()`（集成 RBAC 种子数据）

**目的**：
1. 移除 `create_all`——alembic 不再让程序启动时建表
2. 集成 RBAC 种子数据初始化——让 `init_db()` 成为 lifespan 启动时"业务种子数据就绪"的入口

**修改前**：
```python
async def init_db():
    """初始化数据库 (创建表等)"""
    from src.models.base import Base
    from src.models import user, application, template, template_category, file, config

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("数据库初始化完成")
```

**修改后**：
```python
async def init_db():
    """
    启动初始化入口（lifespan 调用）

    职责：
      - 不再管 schema（schema 由 alembic 部署时负责）
      - 只管"应用启动必需的运行时数据"，如 RBAC 角色/权限码
      - 幂等：每次启动跑无害，不消耗大量资源
    """
    from src.scripts.init_rbac_data import init_rbac_data

    await init_rbac_data()
    logger.info("业务种子数据就绪（RBAC）")
```

**幂等性保证**：

`init_rbac_data.py` 已经是按"SELECT WHERE EXISTS → INSERT"模式写的，**不用担心**：

- ❌ 不会每次启动都重写所有角色/权限码
- ❌ 不会在数据上做 UPDATE（除非代码里明确写）
- ❌ 不会因为重复执行产生重复记录（DB 有 unique 约束兜底）

**每次启动的实际开销**：
- 1 次 SELECT COUNT 查 RBAC 表
- 几条 INSERT（如果表是空的）
- 如果表已经有数据 → 直接 SELECT 后退出，几乎零开销

**为什么 RBAC 放 lifespan 而不是独立脚本**：

| 维度 | lifespan 自动跑 | 独立 init container |
|------|---------------|-------------------|
| 配置复杂度 | 低（FastAPI 自带） | 高（要单独写 k8s job） |
| 跟应用版本同步 | 自动（同一个镜像） | 手动（要拉同一个镜像） |
| 失败处理 | 应用起不来，deploy 失败 | job 失败被吞掉，应用起不来但没日志 |
| 多环境一致性 | 强（一次配置所有环境一致） | 弱（每个环境要单独配） |

→ **lifespan 自动跑** 几乎在所有维度都赢，**独立 init 只在 schema 这种"重型 DDL"场景有意义**。

---

### 步骤 9：部署命令改造

**核心原则**：schema 跟 git commit 绑定，跟 Dockerfile 无关。Dockerfile 只决定"启动时跑什么命令"，具体跑哪个 schema 变更由镜像里 `alembic/versions/` 的内容决定。

**部署时容器启动顺序**（这是 Dockerfile 唯一需要关心的事）：

```
1. alembic upgrade head    ← 按当前镜像里的 migration 把 schema 推到最新
2. uvicorn main:app        ← 启动应用（lifespan 里跑 init_rbac_data 幂等种子）
```

**根据你的部署方式选其一**：

#### 9.1 Docker（推荐：CMD 串联）

**改 `Dockerfile`**——只改最后一行 CMD，把"启动前先跑 migration"显式写出来：

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --timeout 300
COPY . .
ENV PYTHONPATH=/app

# 旧：
# CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

# 新：先 schema 同步，再启动应用
CMD ["sh", "-c", "alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port 8000"]
```

> 注意：`alembic upgrade head` 里**不写具体的 schema 变更**，它只说"跑到当前镜像里 migration 文件对应的 head"。具体变更内容全在 `alembic/versions/*.py` 里（这些文件跟着 git commit 走，Dockerfile 不知道也不需要知道）。

#### 9.2 k8s：用 initContainer

```yaml
initContainers:
  - name: migrate
    image: idbackend:latest
    command: ["alembic", "upgrade", "head"]
containers:
  - name: idbackend
    image: idbackend:latest
    command: ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

#### 9.3 docker-compose（如果后端也走 compose）

在 `command:` 里前置 `alembic upgrade head`：
```yaml
services:
  idbackend:
    build: ./idbackend
    command: >
      sh -c "alembic upgrade head &&
             uvicorn main:app --host 0.0.0.0 --port 8000"
```

#### 9.4 手动部署

```bash
cd /home/dustp/codes/idproject/idbackend
alembic upgrade head
uvicorn main:app --host 0.0.0.0 --port 8000
```

#### 9.5 本地开发

不需要特殊处理。本地开发可以保持现状不跑 alembic（只要 DB 跟 model 一致）。真要本地也跑：
```bash
alembic upgrade head   # 一次性
uvicorn main:app --reload
```

#### 9.6 部署架构澄清（重要！）

本项目部署分 4 层，**职责互不交叉**：

| 层 | 内容 | 维护方式 | 频率 |
|----|------|----------|------|
| **基础设施** | postgres、redis、minio（`docker-compose.infra.yml`） | 服务器手动 `docker compose up -d` | 半年~一年一次 |
| **DB schema** | `src/models/*.py` + `alembic/versions/*.py` | 改 model → autogenerate → commit → 部署时跑 alembic upgrade head | 跟代码变更频率 |
| **业务种子数据** | `src/scripts/init_rbac_data.py`（角色/权限码） | lifespan 启动时跑，幂等 | 每次启动 |
| **应用代码** | FastAPI 路由、业务 service、依赖 | 同 DB schema，绑在同一个 git commit / 镜像 | 每次发版 |

**4 层的关键关系**：

- **基础设施（infra）和应用代码解耦**：infra 用独立 compose，postgres 数据卷不跟着应用镜像走
- **schema 跟业务代码耦合**：必须在同一个 git commit（同一次 commit 改了 model + 改了业务逻辑）
- **RBAC 种子是"应用启动前必须就绪"的依赖**：放 lifespan 里，幂等执行，多跑无害
- **alembic 是 schema 同步的执行者**：它读镜像里的 `alembic/versions/` 文件，按顺序执行 DDL

---

### 步骤 10：完整验证

```bash
cd /home/dustp/codes/idproject/idbackend

# 10.1 启动后端，看 alembic 不报错
uvicorn main:app --host 0.0.0.0 --port 8000
# 应正常启动，不再调 create_all

# 10.2 检查 alembic 状态
alembic current
# 输出：<head_revision> (head)

alembic history --verbose
# 应能看到 init_base_schema 是 head

# 10.3 跑一次 dry-run，确认没遗漏 migration
alembic upgrade head --sql
# 输出应是空（或只有 SELECT 1 之类的探测语句）

# 10.4 测一次 downgrade + upgrade（验证 migration 可逆）
alembic downgrade base    # ← 会删所有表！非生产环境才跑
alembic upgrade head      # ← 应该按 init migration 重建所有表
```

**步骤 10.4 仅在测试环境跑**，生产别跑 `alembic downgrade base`。

---

## 5. 生成 migration 后的 review 检查清单

### 5.1 必查项

打开 `alembic/versions/xxxx_init_base_schema.py`，逐项核对：

- [ ] 包含 20 张表的 CREATE TABLE
- [ ] 所有字段类型、长度、nullable 正确（特别是 `DECIMAL(5,2)`、`String(255)`）
- [ ] 所有外键的 `ondelete` 策略正确（CASCADE / SET NULL）
- [ ] 所有 UniqueConstraint 正确
- [ ] 所有 CheckConstraint 正确（attribute.type、rule.type、template.max_score）
- [ ] 所有 Index 正确
- [ ] 表的创建顺序正确（外键依赖的表先建）

### 5.2 可能出现的"假阳性差异"

**autogenerate 会发现的"不需要修"差异**：

| 现象 | 原因 | 处理 |
|------|------|------|
| DB 有冗余索引 `ix_applications_user_id`（已被 `idx_application_user_template_status` 覆盖） | 历史遗留 | 在 migration 末尾加 `op.drop_index('ix_applications_user_id', table_name='applications')` |
| DB 序列的所有权（`OWNED BY`）差异 | pg_dump 信息，alembic 不跟踪 | 忽略 |
| `table comment` / `column comment` 差异 | alembic 默认不跟踪 COMMENT | 忽略 |
| 字符集 / collation 差异 | alembic 不跟踪 | 忽略 |

**autogenerate 会漏掉的"需要手工补"的差异**：

| 现象 | 原因 | 处理 |
|------|------|------|
| 列重命名（识别成"删一列+加一列"） | autogenerate 用 diff，不识别 rename | 手工改成 `op.alter_column()` |
| 表/列 COMMENT | alembic 默认不生成 | 手动加 `sa.text("COMMENT ...")` |
| `server_default` 中的函数 | 部分场景识别失败 | 手动加 `server_default=sa.text("...")` |

### 5.3 一句话原则

> **如果 migration 内容跟 DB 实际 schema 等价（哪怕多/少几行 index/comment），就是合格的。**

---

## 6. 部署命令改造

> **本章配套阅读**：步骤 9.6（部署架构澄清）。本项目 4 层部署架构详见那里。

### 6.1 部署流水线顺序

```
一次 git commit（包含 models + alembic migration + 业务代码）
                              ↓
                       docker build（打包成镜像）
                              ↓
                       docker run（部署到服务器）
                              ↓
              ┌────────────────────────────────┐
              │ 容器启动                        │
              │                                │
              │  1. alembic upgrade head       │ ← 按镜像里带的 migration 文件跑
              │  2. uvicorn main:app           │ ← lifespan 跑 init_rbac_data
              │     （lifespan 触发）           │   幂等种子数据
              └────────────────────────────────┘
```

### 6.2 Dockerfile 在这套架构里的角色

**Dockerfile 不关心 schema**。它只决定：

1. 怎么准备运行环境（Python 版本、装什么依赖）
2. 怎么打包代码 COPY 进去
3. 容器启动时跑什么命令（CMD）

```dockerfile
# 典型 idbackend Dockerfile（切 Alembic 后）
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --timeout 300
COPY . .                          ← models、alembic、business code 一起 COPY
ENV PYTHONPATH=/app
CMD ["sh", "-c", "alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port 8000"]
```

> "改 schema"这件事——它的实现细节（"加哪一列""删哪个索引"）全在 `alembic/versions/*.py` 里，由 git commit 决定。Dockerfile 不需要改一行就自动跟着新 schema 走。

### 6.3 关键点

- **alembic 必须先于应用启动**：否则应用启动时 SQL 查询命中旧 schema，或者 `init_rbac_data()` 引用了还不存在的表
- **如果用 k8s**：用 initContainer，失败时阻塞主容器启动
- **如果用 docker compose**：用 `command:` 串联，或写启动脚本
- **postgres / redis / minio 不在应用镜像里**：它们由 `docker-compose.infra.yml` 单独维护，跟应用部署解耦

### 6.4 不要做的

- ❌ 不要让 `init_db()` 仍调 `create_all`，跟 alembic 双重管理会冲突
- ❌ 不要在 `lifespan` 里跑 `alembic upgrade head`（同步阻塞事件循环，且应用进程该只管跑业务；schema 同步应该是部署时的"前置步骤"，不是应用启动的一部分）
- ❌ 不要在 web 请求处理中跑 alembic
- ❌ 不要把 schema 变更逻辑硬编码到 Dockerfile 里（保持 Dockerfile 通用，变更逻辑放 migration 文件）

---

## 7. 日常开发流程（切换完成后）

### 7.1 加一个新字段

```python
# src/models/user.py
class User(Base, TimestampMixin):
    ...
    email: Mapped[Optional[str]] = mapped_column(String(255))   # 新加
```

```bash
# 生成 migration
alembic revision --autogenerate -m "add user.email"

# 打开 alembic/versions/xxxx_add_user_email.py review
# 必须看一遍！

# 本地测试
alembic upgrade head

# 提交
git add alembic/versions/xxxx_add_user_email.py
git commit -m "feat(model): add user.email"
```

### 7.2 删一个字段

```bash
# 1. 改 model
# 2. 跑 autogenerate
alembic revision --autogenerate -m "drop user.deprecated_field"
# 3. review migration（注意：删字段会丢数据！）
# 4. 如果是有数据字段，应先写数据迁移 SQL，再删字段
```

### 7.3 重命名字段

```python
# ⚠️ autogenerate 会识别成"删+加"，会丢数据！
# 必须手工编辑 migration：
def upgrade():
    op.alter_column('users', 'old_name', new_column_name='new_name')

def downgrade():
    op.alter_column('users', 'new_name', new_column_name='old_name')
```

### 7.4 review checklist（每次生成 migration 必看）

- [ ] 没有 `drop column` 含数据的字段
- [ ] 没有"删表"的 destructive 操作（除非确认是测试表）
- [ ] `downgrade()` 是否可逆（生产可能紧急回滚）
- [ ] 索引/约束都正确

---

## 8. 常见坑 & 注意事项

### 8.1 驱动问题

| 场景 | 现象 | 解决 |
|------|------|------|
| `alembic` 用 async 模型 | `RuntimeError` | env.py 用 sync engine，让 alembic 自己处理 |
| `pip install alembic` 没装 `psycopg2-binary` | `ImportError: No module named psycopg2` | `pip install psycopg2-binary` |
| `DATABASE_URL` 是 `postgresql+asyncpg://` | alembic 不识别 | env.py 里 sed 改成 `postgresql+psycopg2://` |

### 8.2 模型导入问题

`env.py` 里 `from src.models.base import Base` 后，必须确保所有 model 都被 import，否则 autogenerate 看不到：

```python
# alembic/env.py
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

from src.models.base import Base
import src.models  # 这一行很关键——触发 __init__.py 里所有 model 的 import

config.set_main_option("sqlalchemy.url", os.getenv("DATABASE_URL"))
target_metadata = Base.metadata
```

`src/models/__init__.py` 已经导出了所有 model（已确认），所以 `import src.models` 即可。

### 8.3 不删除 `Base.metadata` 里的内容

alembic 完全靠 `Base.metadata` 知道模型。如果某个 model 文件没被 import，autogenerate 会"看不到"它，生成出来的 migration 会试图 DROP 那个 model 的表。

**防范**：永远保证 `src/models/__init__.py` 包含所有 model，并确保 `env.py` 显式 import `src.models`。

### 8.4 多人协作时

- 多个分支同时改 model → 各自的 migration 文件名（基于时间戳）不会冲突
- 但合并后可能"out-of-order"（两个分支的 migration 顺序错），用 `alembic merge` 解决：

```bash
alembic merge -m "merge heads" <rev1> <rev2>
```

### 8.5 不要删 `alembic_version` 表

这表是 alembic 的状态记录，删了下次 `alembic current` 报错。

---

## 9. 回滚预案

### 9.1 如果切换后启动失败

```bash
# 1. 看 alembic 状态
alembic current
alembic history

# 2. 如果是 env.py 配置错，修改后重试
# 3. 如果是 migration 内容错
alembic downgrade -1   # 回滚一个
# 或
alembic downgrade base # 回滚所有（会删表！生产别用）

# 4. 如果整个 alembic 出问题，临时回退到旧方式：
#    - 把 init_db() 恢复 create_all
#    - 删除 alembic_version 表
```

### 9.2 紧急回退到原"手写 migration + create_all"模式

```bash
# 1. 从 git 恢复 src/migrations/、migrations/、clean_user_fields.py
git checkout HEAD~N -- src/migrations/ migrations/ src/migrations/clean_user_fields.py
# 2. 恢复 database.py 的 init_db()
git checkout HEAD~N -- src/infra/database.py
# 3. 删除 alembic_version 表
psql ... -c "DROP TABLE IF EXISTS alembic_version;"
```

---

## 10. 切换完成 checklist（自检）

- [ ] `pip install alembic` 完成，`requirements.txt` 更新
- [ ] `alembic init alembic` 成功，目录结构正确
- [ ] `alembic/env.py` 改造完成，能读到 `.env` 的 `DATABASE_URL`
- [ ] `alembic revision --autogenerate -m "init_base_schema"` 成功生成 migration
- [ ] **手工 review** migration 内容，确认等价于 20 张表的 schema
- [ ] `alembic stamp head` 执行成功，`alembic_version` 表已建
- [ ] `migrations/`（项目根）已删除
- [ ] `src/migrations/clean_user_fields.py` 已删除
- [ ] `src/infra/database.py` 的 `init_db()` 不再调 `create_all`，改为调 `init_rbac_data()`（幂等种子）
- [ ] `Dockerfile` 的 `CMD` 已加 `alembic upgrade head &&` 前缀（schema 同步前置）
- [ ] 本地启动验证：应用正常跑，`alembic current` 显示 `(head)`
- [ ] 确认 `docker-compose.infra.yml` 的基础设施未受影响（postgres/redis/minio 还在独立维护）

---

## 附录：最终目录结构（切换后）

```
idbackend/
├── alembic/                              ← 新增
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── xxxx_init_base_schema.py      ← 第一个 migration（base schema）
│       └── xxxx_add_user_email.py        ← 后续 PR 带的增量 migration
├── alembic.ini                            ← 新增
├── docs/
│   └── base/
│       ├── alembic-migration-checklist.md ← 本文档
│       └── response_struct.md
├── main.py
├── src/
│   ├── migrations/                        ← 删除（已无文件）
│   ├── models/                            ← schema 定义（git 改动源头）
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── user.py
│   │   ├── application.py
│   │   └── ...
│   ├── scripts/
│   │   └── init_rbac_data.py              ← lifespan 启动时幂等跑
│   ├── infra/
│   │   └── database.py                    ← init_db() 调 init_rbac_data，不再 create_all
│   └── app/
├── migrations/                            ← 删除（项目根的 22 个手写文件）
├── requirements.txt                       ← 加 alembic
├── Dockerfile                             ← 只改最后一行 CMD 串联 alembic upgrade head
└── ...
```

**部署分层对应表**：

| 层 | 文件位置 | 维护频率 |
|----|---------|---------|
| 基础设施 | 仓库根 `/docker-compose.infra.yml` + 服务器上挂的数据卷 | 半年~一年 |
| DB schema | `idbackend/src/models/*.py` + `idbackend/alembic/versions/*.py` | 每次 schema 变更 |
| 业务种子 | `idbackend/src/scripts/init_rbac_data.py` | RBAC 设计变更时 |
| 应用代码 | `idbackend/src/**/*.py` + `idbackend/main.py` | 每次发版 |

---

*文档版本：1.2*
*生成日期：2026-07-11*
*更新说明：*
- *v1.1 修正第 6 章"部署命令改造"——明确 schema 跟 git commit 绑定（不是跟 Dockerfile 绑定），补充 4 层部署架构（基础设施/schema/RBAC 种子/应用代码）*
- *v1.2 步骤 8 改写为"集成 RBAC 种子数据到 init_db()"（替换之前的"二选一"模糊措辞），并补充幂等性说明与 lifespan vs init container 对比*
*前置依据：idinfra/iddata-2026-07-11_133038-dump.sql vs src/models/ 比对通过*