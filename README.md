# idbackend

厦门大学信息学院保研加分助手后端。FastAPI + LangGraph，提供认证、加分申请、审核、AI 对话、知识库 RAG。

## 技术栈

FastAPI · SQLAlchemy 2.0 + asyncpg · PostgreSQL + pgvector · Redis · MinIO（S3）· LangGraph · JWT

## 目录结构

```
src/
├── main.py              # 启动入口（uvicorn main:app）
├── app/                 # HTTP 层（routes / schemas / middleware / deps）
├── services/            # 业务逻辑
├── repositories/        # 数据库访问
├── models/              # SQLAlchemy ORM
├── agent/               # LangGraph Agent（graph / nodes / tools / rag）
└── infra/               # 配置 / DB / Redis / S3 / JWT / 邮件
tests/                  # pytest
```

分层：`router → service → repository → model`，Agent 工具直接调 service。

## 快速启动

### 0. 前置

- Python 3.11+
- 本地已起好 PostgreSQL（带 pgvector）、Redis、MinIO 三件套（基础设施不在本仓维护，由运维/SRE 提供）

### 1. 装依赖

```bash
pip install -r requirements.txt
```

### 2. 改 .env

仓库已带 `.env`，**默认连远端服务器**（`223.109.49.63`）。本地开发请改成你自己的环境：

```bash
DATABASE_URL=postgresql://<user>:<password>@localhost:5432/iddata
PG_VECTOR_URL=postgresql://<user>:<password>@localhost:5432/iddata
REDIS_URL=redis://:<password>@localhost:6379/1
MINIO_ENDPOINT=http://localhost:9000
MINIO_ACCESS_KEY=<your-access-key>
MINIO_SECRET_KEY=<your-secret-key>
MINIO_BUCKET=idbucket
```

并确保数据库 `iddata` 已建好（本地连上 PG 后 `CREATE DATABASE iddata;`）。

### 3. 跑

```bash
python main.py          # 推荐：自动同步 schema + uvicorn
# 或
uvicorn main:app --reload --port 8000   # 热重载
```

访问 `http://localhost:8000/docs` 看 Swagger。

### 4. 测试

```bash
pytest tests/ -v
```

## API 路由速查

| 前缀 | 说明 |
|------|------|
| `/api/auth` | 登录 / 注册 / 验证码 |
| `/api/users` | 用户管理 |
| `/api/applications` | 加分申请 |
| `/api/templates` | 模板管理 |
| `/api/files` | 文件管理 |
| `/health` | 健康检查 |

## 常见问题

**Q: 启动报 `connection refused` / 连不上 Postgres**
A: 检查 `.env` 的 `DATABASE_URL` 是否指向正确的地址 + 端口；本地 PG 默认端口 5432，需 PG 本身在运行；`psql -U <user> -h localhost -d iddata` 验证能直连。

**Q: schema 没建 / 表不存在**
A: `Base.metadata.create_all` 启动时自动建——前提是能连上 PG，且 `iddata` 数据库已存在。
手工建：`psql -U <user> -h localhost -c "CREATE DATABASE iddata;"`

**Q: pgvector 报错 `type "vector" does not exist`**
A: 本地装的 PG 镜像必须是带 pgvector 扩展的版本（如 `postgres:17` + 手动 `CREATE EXTENSION vector;`，或 `eyeix/postgres-zh:v17` 内置）。

**Q: MinIO 上传 403 / 连接超时**
A: 检查 `.env` 的 `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` 与 MinIO 服务端的 access/secret 一致；`MINIO_ENDPOINT` 用 `localhost:9000`（容器外部端口）而非内网 IP。

**Q: imports 报错 `src.xxx`**
A: 用 `python main.py` 启动（main.py 已设置 `PYTHONPATH` 并做 schema 同步）。若 IDE 飘红，安装完依赖后重启 IDE / reload 解释器。

**Q: LLM / Embedding 报错**
A: 检查 `.env` 的 `LLM_API_KEY` / `EMBEDDING_API_KEY` 与 `*_BASE_URL` / `*_MODEL` 是否填写完整。

**Q: 端口 8000 被占用**
A: 改 `.env` 的 `PORT=8001`，前端相应改 `vite.config.ts` 的 `proxy['/api'].target`。

**Q: 想要干净的本地默认配置**
A: 拷贝 `.env.example`（如果未来添加）作为本地模板；当前 `.env` 是带远端 IP 的实例值，必须手动改。