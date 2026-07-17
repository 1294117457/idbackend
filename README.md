# ID-Python 统一后端

FastAPI + LangGraph 实现的保研加分助手后端服务，统一管理用户认证、加分申请、审核流程和 AI 对话功能。
1
## 技术栈

- **Web 框架**: FastAPI 0.115+
- **Agent 编排**: LangGraph 0.1+
- **ORM**: SQLAlchemy 2.0 + asyncpg
- **数据库**: PostgreSQL + pgvector
- **缓存**: Redis
- **文件存储**: SeaweedFS (S3兼容)
- **认证**: JWT (python-jose) + bcrypt

## 项目结构

```
idpython/
├── src/
│   ├── main.py              # 应用入口
│   ├── app/                 # HTTP层
│   │   ├── routes/         # FastAPI路由
│   │   ├── schemas/        # Pydantic模型
│   │   ├── deps.py         # 依赖注入
│   │   └── response.py     # 响应工具
│   ├── services/           # 业务逻辑层
│   ├── models/            # SQLAlchemy模型
│   ├── agent/             # LangGraph Agent
│   │   ├── graph/         # 图定义
│   │   ├── nodes/         # 节点
│   │   └── tools/         # Agent工具 (直接调用services)
│   ├── rag/               # 知识库RAG
│   └── infra/             # 基础设施
│       ├── config.py      # pydantic-settings
│       ├── database.py    # PostgreSQL
│       ├── redis.py       # Redis
│       ├── s3.py          # SeaweedFS
│       ├── jwt.py         # JWT工具
│       └── email.py       # 邮件发送
├── tests/                 # 测试
├── requirements.txt       # 依赖
├── .env                  # 环境变量
├── Dockerfile
└── README.md
```

## 快速开始

### 1. 安装依赖

```bash
cd idpython
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填入配置
```

### 3. 运行服务

```bash
# 开发模式
uvicorn main:app --reload --port 8000

# 生产模式
uvicorn main:app --host 0.0.0.0 --port 8000
```

### 4. 运行测试

```bash
pytest tests/ -v
```

## API 路由

| 前缀 | 说明 |
|------|------|
| `/api/auth` | 认证 (登录/注册/验证码) |
| `/api/users` | 用户管理 |
| `/api/applications` | 加分申请 |
| `/api/templates` | 模板管理 |
| `/api/files` | 文件管理 |
| `/health` | 健康检查 |

## Docker 部署

```bash
docker build -t idpython .
docker run -p 8000:8000 --env-file .env idpython
```

## 环境变量

```bash
# 数据库
DATABASE_URL=postgresql://user:pass@localhost:5432/idproject

# Redis
REDIS_URL=redis://localhost:6379/0

# SeaweedFS (S3)
S3_ENDPOINT=http://localhost:8333
S3_ACCESS_KEY=your_key
S3_SECRET_KEY=your_secret
S3_BUCKET=idproject

# JWT
JWT_SECRET=your-secret-key
JWT_ALGORITHM=HS256
JWT_EXPIRE_HOURS=24

# LLM
QWEN3_API_KEY=your-api-key
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

## License

MIT
