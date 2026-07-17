# Step 1 · 基础设施准备

> 本步目标：**让 PostgreSQL 支持向量检索、补齐 ORM / 配置 / 依赖**，把 RAG 和 Agent 需要的"地基"打好。
> 本步**不写任何业务代码**，只动模型、依赖、配置、迁移脚本。

---

## 1. 任务清单

| # | 任务 | 文件 | 关键点 |
|---|------|------|--------|
| 1.1 | 安装 pgvector 扩展 | PostgreSQL 服务器 | `CREATE EXTENSION vector;` |
| 1.2 | 加 Python 依赖 | `requirements.txt` | `pgvector`, `tiktoken`, `langchain-postgres`（可选） |
| 1.3 | 改造 `PolicyDocument` 模型 | `src/models/file.py` | `embedding` 列改 `pgvector.Vector(1024)` |
| 1.4 | 新增 `TemplateEmbedding` 模型 | `src/models/template_embedding.py`（新建） | 存 template 自身的语义索引 |
| 1.5 | 新增枚举 `FileCategory.PROOF_TEMP` | `src/models/file.py` | 临时证明材料，孤儿清理用 |
| 1.6 | 检查 `AgentSession` / 新增 `AgentMessage` | `src/models/config.py` | 会话持久化用 |
| 1.7 | config 加 Qwen / pgvector 配置 | `src/infra/config.py` | 已有 `QWEN_*`，补 `QWEN_EMBEDDING_DIM` 等 |
| 1.8 | 启动时建表 + 建索引 | `src/main.py` 或新启动钩子 | HNSW 索引建在 `policy_documents.embedding` 上 |
| 1.9 | 加 4 个 RBAC 权限码 | `src/scripts/init_rbac_data.py` | `ai:chat`, `ai:knowledge:*`, `ai:config:*` |

---

## 2. 详细步骤

### 2.1 安装 pgvector 扩展

```bash
# 以 postgres 超级用户连库
psql "$DATABASE_URL" -c "CREATE EXTENSION IF NOT EXISTS vector;"
# 验证
psql "$DATABASE_URL" -c "SELECT extname, extversion FROM pg_extension WHERE extname='vector';"
```

> 生产环境如果 DBA 不给超级用户权限，请 DBA 执行；测试环境直接 root。

### 2.2 Python 依赖追加

`requirements.txt` 在 `langgraph>=0.1.0` 后面追加：

```text
langgraph>=0.1.0
langchain>=0.3.0
langchain-community>=0.3.0
langchain-openai>=0.2.0
langchain-text-splitters>=0.3.0
pgvector>=0.3.6
tiktoken>=0.7.0
```

安装：

```bash
cd /home/dustp/codes/idproject/idbackend
source .venv/bin/activate
pip install pgvector tiktoken
```

### 2.3 改造 `PolicyDocument` 模型

`src/models/file.py` 第 67 行：

```python
# 原
embedding: Mapped[Optional[str]] = mapped_column(String)
# 改为
from pgvector.sqlalchemy import Vector
embedding: Mapped[Optional[List[float]]] = mapped_column(Vector(1024), nullable=True)
```

### 2.4 新增 `TemplateEmbedding` 模型

新建 `src/models/template_embedding.py`：

```python
"""Template 语义索引表（用于 RAG 召回 template 候选）"""
from sqlalchemy import Integer, String, ForeignKey, Boolean, Index
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional

from pgvector.sqlalchemy import Vector
from .base import Base, TimestampMixin


class TemplateEmbedding(Base, TimestampMixin):
    """template 自身的语义索引

    触发时机：TemplateService.create / update / save_template 之后异步重建。
    """
    __tablename__ = "template_embeddings"

    template_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("template.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    # 拼接的索引文本：name + description + rules.name + attributes.name
    content_text: Mapped[str] = mapped_column(String, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[Optional[List[float]]] = mapped_column(Vector(1024), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    __table_args__ = (
        Index("ix_template_embedding_active", "is_active"),
    )
```

`src/models/__init__.py` 加导出：

```python
from src.models.template_embedding import TemplateEmbedding
```

### 2.5 新增 `FileCategory.PROOF_TEMP`

`src/models/file.py` 第 10-14 行：

```python
class FileCategory(str, enum.Enum):
    AVATAR = "AVATAR"
    PROOF = "PROOF"
    POLICY = "POLICY"
    PROOF_TEMP = "PROOF_TEMP"   # ← 新增：临时证明材料（agent 分析中）
```

### 2.6 检查 / 新增 `AgentMessage`

打开 `src/models/config.py`，确认 `AgentSession` 字段，再新建 `AgentMessage`：

```python
class AgentMessage(Base, TimestampMixin):
    """agent 单条消息"""
    __tablename__ = "agent_message"

    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_session.session_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user/assistant/system/interrupt
    content: Mapped[str] = mapped_column(String, nullable=False)
    msg_type: Mapped[str] = mapped_column(String(30), nullable=False)  # text/suggestion/file_event/...
    extra_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)  # 同 session 内自增顺序

    __table_args__ = (
        Index("ix_agent_message_session_seq", "session_id", "seq"),
    )
```

### 2.7 config 追加

`src/infra/config.py` 已有字段：

```python
QWEN3_API_KEY: str = ""
QWEN_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
QWEN_CHAT_MODEL: str = "qwen3-max"
QWEN_EMBEDDING_MODEL: str = "text-embedding-v3"
CONTEXT_MAX_MESSAGES: int = 20
```

新增：

```python
# RAG
QWEN_EMBEDDING_DIM: int = 1024
RAG_CHUNK_SIZE: int = 500
RAG_CHUNK_OVERLAP: int = 50
RAG_TOP_K_VECTOR: int = 10
RAG_TOP_K_KEYWORD: int = 6
RAG_TOP_K_FINAL: int = 5
RAG_RRF_K: int = 60

# Agent
AGENT_MAX_TOKENS_PER_TURN: int = 4096
AGENT_TEMPERATURE: float = 0.3
AGENT_INTERRUPT_TIMEOUT_SECONDS: int = 600  # 10 分钟不响应就过期

# 临时文件清理（分钟）
PROOF_TEMP_TTL_MINUTES: int = 60
```

### 2.8 启动钩子：建表 + HNSW 索引

`src/main.py`（或新建 `src/infra/db_init.py`）里加：

```python
async def init_vector_indexes():
    """启动时建 HNSW 索引（IF NOT EXISTS 幂等）"""
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_policy_embedding_hnsw
            ON policy_documents
            USING hnsw (embedding vector_cosine_ops)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_template_embedding_hnsw
            ON template_embeddings
            USING hnsw (embedding vector_cosine_ops)
        """))
```

> ⚠️ HNSW 索引不能用 `create_all()` 自动建（SQLAlchemy 不识别），必须用 raw SQL。

### 2.9 新增 RBAC 权限码

`src/scripts/init_rbac_data.py` 的 `PERMISSIONS_DATA` 里加 6 行（详见 `docs/step1/rbac/02-init-permissions.md` 的格式）：

```python
("ai:chat",                  "AI 对话",       "/ai/agent/stream",          "ai",     "智能助手", 100),
("ai:chat",                  "AI 对话",       "/ai/agent/resume-stream",   "ai",     "智能助手", 100),
("ai:knowledge:read",        "知识库查看",     "/ai/knowledge/list",        "ai",     "知识库",   110),
("ai:knowledge:read",        "知识库查看",     "/ai/knowledge/stats",       "ai",     "知识库",   110),
("ai:knowledge:write",       "知识库管理",     "/ai/knowledge/upload",      "ai",     "知识库",   111),
("ai:knowledge:write",       "知识库管理",     "/ai/knowledge/{file}",      "ai",     "知识库",   111),
("ai:config:read",           "AI 配置查看",    "/ai/config/",               "ai",     "AI 配置",  120),
("ai:config:write",          "AI 配置管理",    "/ai/config/",               "ai",     "AI 配置",  120),
```

`ROLE_PERMISSIONS` 给 `super_admin / admin` 加 `ai:knowledge:write`、`ai:config:write`；给 `user` 加 `ai:chat`。

跑：

```bash
python -m src.scripts.init_rbac_data
```

---

## 3. 验收

```bash
# 1. 扩展安装成功
psql "$DATABASE_URL" -c "SELECT extversion FROM pg_extension WHERE extname='vector';"

# 2. 模型导入无报错
cd /home/dustp/codes/idproject/idbackend
source .venv/bin/activate
python -c "from src.models import TemplateEmbedding, AgentMessage; print('ok')"

# 3. 启动服务时控制台能看到 "HNSW indexes created"

# 4. RBAC 权限码已写入
psql "$DATABASE_URL" -c "SELECT permission_code FROM permission WHERE permission_code LIKE 'ai:%' ORDER BY permission_code;"
```

预期：

```
 extversion
------------
 0.7.x
ok
HNSW indexes created

       permission_code
---------------------------
 ai:chat
 ai:config:read
 ai:config:write
 ai:knowledge:read
 ai:knowledge:write
```

---

## 4. 下一步

完成本步后，进入 [`02-rag.md`](./02-rag.md) 实现 RAG 完整逻辑（chunker / embeddings / store / 混合检索 / 管理端 CRUD）。