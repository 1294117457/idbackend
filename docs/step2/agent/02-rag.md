# Step 2 · RAG 知识库搭建

> 本步目标：把 `src/rag/` 从 TODO 空壳**完整实现**，打通「管理员上传政策文件 → 自动切块 → embedding → 存 pgvector → 混合检索」整条链路，并把 CRUD 接口暴露给管理端。
> 本步**不**写 agent graph（留给 Step 3），只产出 `rag/` 包 + 一个 `policy_service` + 4 个路由。

---

## 1. 任务清单

| # | 任务 | 文件 | 关键点 |
|---|------|------|--------|
| 2.1 | OCR / 文件解析 | `src/rag/file_parser.py`（改造） | pdfplumber / mammoth / openpyxl |
| 2.2 | 切块器 | `src/rag/chunker.py`（新建） | 按段落 + 字符数双约束 |
| 2.3 | Qwen Embedding 封装 | `src/rag/embeddings.py`（新建） | 批量、失败重试 |
| 2.4 | 向量存储 | `src/rag/store.py`（新建） | pgvector 增删查 + 余弦相似度 |
| 2.5 | 混合检索 | `src/rag/search.py`（改造） | RRF 融合向量 + PG full-text |
| 2.6 | `policy_documents` 增 full-text 列 | SQL 迁移 | `tsvector` + GIN 索引 |
| 2.7 | `policy_repo` / `policy_service` | `src/repositories/policy_repo.py`、`src/services/policy_service.py`（新建） | 严格遵循分层 |
| 2.8 | `policy.py` schema | `src/app/schemas/policy.py`（新建） | Request / VO / ListVO |
| 2.9 | `policy.py` 路由 | `src/app/routes/policy.py`（新建） | 上传 / 列表 / 删除 / 检索 |
| 2.10 | `template_indexer.py`（新建） | `src/rag/template_indexer.py` | template 增删改后异步索引 |

---

## 2. 详细设计

### 2.1 文件解析 `rag/file_parser.py`

```python
"""文件解析 - 把任意格式转为纯文本"""
from typing import Optional
import io

def parse_file_to_text(content: bytes, filename: str) -> str:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext == "pdf":
        return _parse_pdf(content)
    elif ext == "docx":
        return _parse_docx(content)
    elif ext == "doc":
        return _parse_docx(content)  # mammoth 兼容
    elif ext in ("xlsx", "xls"):
        return _parse_xlsx(content)
    elif ext in ("txt", "md"):
        return content.decode("utf-8", errors="ignore")
    return ""

def _parse_pdf(content: bytes) -> str:
    import pdfplumber
    text_parts = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            text_parts.append(page.extract_text() or "")
    return "\n\n".join(text_parts)

def _parse_docx(content: bytes) -> str:
    import mammoth
    result = mammoth.extract_raw_text(io.BytesIO(content))
    return result.value or ""

def _parse_xlsx(content: bytes) -> str:
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    parts = []
    for sheet in wb.worksheets:
        for row in sheet.iter_rows(values_only=True):
            line = " | ".join(str(c) if c is not None else "" for c in row)
            if line.strip(" |"):
                parts.append(line)
    return "\n".join(parts)
```

### 2.2 切块器 `rag/chunker.py`

策略：**段落优先 + 字符硬截断**。理由：政策文档多是结构化的，先按 `\n\n` 切段；如果段落过长再按字符数硬切；段落之间留 overlap 保证语义连贯。

```python
"""切块器"""
from typing import List
from dataclasses import dataclass

@dataclass
class Chunk:
    text: str
    index: int         # 在原文中的顺序
    char_start: int
    char_end: int

def split_text(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50,
) -> List[Chunk]:
    """先按段落切，段落过长再按字符切"""
    if not text or not text.strip():
        return []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: List[Chunk] = []
    current_text = ""
    current_start = 0
    char_pos = 0
    idx = 0

    for para in paragraphs:
        # 段落本身就超长：硬切
        if len(para) > chunk_size:
            if current_text:
                chunks.append(Chunk(current_text, idx, current_start, char_pos))
                idx += 1
                current_text = ""
            for i in range(0, len(para), chunk_size - overlap):
                sub = para[i:i + chunk_size]
                chunks.append(Chunk(sub, idx, char_pos + i, char_pos + i + len(sub)))
                idx += 1
            char_pos += len(para) + 2
            current_start = char_pos
            continue

        # 段落 + 当前 buffer 超长：先 flush 当前 buffer
        if len(current_text) + len(para) + 2 > chunk_size and current_text:
            chunks.append(Chunk(current_text, idx, current_start, char_pos))
            idx += 1
            # overlap：保留 current_text 末尾 overlap 字符
            tail = current_text[-overlap:] if len(current_text) > overlap else current_text
            current_text = tail + "\n\n" + para
            current_start = char_pos - len(tail)
        else:
            current_text = (current_text + "\n\n" + para) if current_text else para

        char_pos += len(para) + 2

    if current_text:
        chunks.append(Chunk(current_text, idx, current_start, char_pos))

    return chunks
```

### 2.3 Embedding 封装 `rag/embeddings.py`

```python
"""Qwen Embedding 封装"""
from typing import List
import asyncio
from openai import AsyncOpenAI
from src.infra.config import get_settings

_settings = get_settings()

class QwenEmbeddings:
    """text-embedding-v3 封装
    
    - 批量调用（每批 ≤ 10）
    - 失败重试（最多 3 次）
    - 默认维度 1024
    """
    BATCH_SIZE = 10
    MAX_RETRIES = 3

    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=_settings.QWEN3_API_KEY,
            base_url=_settings.QWEN_BASE_URL,
        )
        self.model = _settings.QWEN_EMBEDDING_MODEL

    async def embed(self, text: str) -> List[float]:
        """单条 embedding"""
        result = await self.embed_batch([text])
        return result[0]

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """批量 embedding"""
        all_results: List[List[float]] = []
        for i in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[i:i + self.BATCH_SIZE]
            for retry in range(self.MAX_RETRIES):
                try:
                    resp = await self.client.embeddings.create(
                        model=self.model,
                        input=batch,
                        dimensions=_settings.QWEN_EMBEDDING_DIM,
                    )
                    all_results.extend([d.embedding for d in resp.data])
                    break
                except Exception as e:
                    if retry == self.MAX_RETRIES - 1:
                        raise
                    await asyncio.sleep(2 ** retry)
        return all_results


# 全局单例
_embeddings: QwenEmbeddings | None = None

def get_embeddings() -> QwenEmbeddings:
    global _embeddings
    if _embeddings is None:
        _embeddings = QwenEmbeddings()
    return _embeddings
```

### 2.4 向量存储 `rag/store.py`

```python
"""pgvector 向量存储"""
from typing import List, Optional
from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.file import PolicyDocument
from src.models.template_embedding import TemplateEmbedding
from src.infra.config import get_settings

_settings = get_settings()


class VectorStore:
    """向量存储封装"""

    async def upsert_policy_chunk(
        self,
        db: AsyncSession,
        *,
        title: str,
        content: str,
        category: Optional[str],
        source_url: Optional[str],
        embedding: List[float],
        doc_metadata: Optional[dict] = None,
    ) -> PolicyDocument:
        """插入或更新政策片段（按 title+content 唯一）"""
        # 简化：直接 INSERT，靠 service 层做"同一文档聚合"
        doc = PolicyDocument(
            title=title,
            content=content,
            category=category,
            source_url=source_url,
            embedding=embedding,
            doc_metadata=doc_metadata or {},
            is_active=True,
        )
        db.add(doc)
        await db.flush()
        return doc

    async def delete_policy_by_source(
        self,
        db: AsyncSession,
        *,
        title_prefix: str,
    ) -> int:
        """按 source_url 删除（管理端删文件用）"""
        result = await db.execute(
            select(PolicyDocument).where(PolicyDocument.title.like(f"{title_prefix}%"))
        )
        docs = result.scalars().all()
        for d in docs:
            await db.delete(d)
        await db.flush()
        return len(docs)

    async def vector_search(
        self,
        db: AsyncSession,
        query_embedding: List[float],
        *,
        top_k: int = None,
    ) -> List[dict]:
        """余弦相似度检索 policy_documents"""
        top_k = top_k or _settings.RAG_TOP_K_VECTOR
        # pgvector 余弦距离：<=>(embedding, query)，越小越相似
        sql = text("""
            SELECT id, title, content, category,
                   1 - (embedding <=> CAST(:query AS vector)) AS score
            FROM policy_documents
            WHERE is_active = TRUE AND embedding IS NOT NULL
            ORDER BY embedding <=> CAST(:query AS vector)
            LIMIT :limit
        """)
        result = await db.execute(sql, {"query": query_embedding, "limit": top_k})
        rows = result.mappings().all()
        return [dict(r) for r in rows]

    async def vector_search_templates(
        self,
        db: AsyncSession,
        query_embedding: List[float],
        *,
        top_k: int = None,
    ) -> List[dict]:
        """检索 template_embeddings，返回 template_id + score"""
        top_k = top_k or _settings.RAG_TOP_K_VECTOR
        sql = text("""
            SELECT template_id,
                   1 - (embedding <=> CAST(:query AS vector)) AS score
            FROM template_embeddings
            WHERE is_active = TRUE AND embedding IS NOT NULL
            ORDER BY embedding <=> CAST(:query AS vector)
            LIMIT :limit
        """)
        result = await db.execute(sql, {"query": query_embedding, "limit": top_k})
        return [dict(r) for r in result.mappings().all()]
```

### 2.5 混合检索 `rag/search.py`

```python
"""混合检索：向量 + 关键词 (PG full-text)"""
from typing import List
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.rag.store import VectorStore
from src.rag.embeddings import get_embeddings
from src.infra.config import get_settings

_settings = get_settings()


def rrf_merge(
    vec_results: List[dict],
    kw_results: List[dict],
    *,
    k: int = 60,
    score_key: str = "score",
    id_key: str = "id",
) -> List[dict]:
    """Reciprocal Rank Fusion"""
    scores: dict[str, float] = {}
    items: dict[str, dict] = {}

    for rank, item in enumerate(vec_results, start=1):
        key = item[id_key]
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
        items[key] = item

    for rank, item in enumerate(kw_results, start=1):
        key = item[id_key]
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
        items[key] = items.get(key, item)

    merged = []
    for key, sc in sorted(scores.items(), key=lambda x: -x[1]):
        item = dict(items[key])
        item["rrf_score"] = sc
        merged.append(item)
    return merged


async def hybrid_search_policy(
    db: AsyncSession,
    query: str,
    *,
    top_k: int = None,
) -> List[dict]:
    """policy 文档混合检索"""
    top_k = top_k or _settings.RAG_TOP_K_FINAL
    embeddings = get_embeddings()
    store = VectorStore()

    # 1) 向量召回
    vec_emb = await embeddings.embed(query)
    vec_results = await store.vector_search(db, vec_emb, top_k=_settings.RAG_TOP_K_VECTOR)

    # 2) 关键词召回 (to_tsquery 'simple' 简化分词，中文友好)
    kw_sql = text("""
        SELECT id, title, content, category,
               ts_rank(to_tsvector('simple', title || ' ' || content),
                       plainto_tsquery('simple', :query)) AS score
        FROM policy_documents
        WHERE is_active = TRUE
          AND to_tsvector('simple', title || ' ' || content)
              @@ plainto_tsquery('simple', :query)
        ORDER BY score DESC
        LIMIT :limit
    """)
    kw_rows = await db.execute(kw_sql, {
        "query": query,
        "limit": _settings.RAG_TOP_K_KEYWORD,
    })
    kw_results = [dict(r) for r in kw_rows.mappings().all()]

    return rrf_merge(vec_results, kw_results, k=_settings.RAG_RRF_K)[:top_k]


async def hybrid_search_templates(
    db: AsyncSession,
    query: str,
    *,
    top_k: int = None,
) -> List[dict]:
    """template 混合检索"""
    top_k = top_k or _settings.RAG_TOP_K_FINAL
    embeddings = get_embeddings()
    store = VectorStore()

    vec_emb = await embeddings.embed(query)
    vec_results = await store.vector_search_templates(db, vec_emb, top_k=_settings.RAG_TOP_K_VECTOR)

    # template 表没有 tsvector 列，纯向量检索即可
    return vec_results[:top_k]
```

### 2.6 policy_documents 增 full-text 列

SQL 迁移脚本（手写 + 重启时自动跑）：

```sql
-- src/scripts/migrations/add_policy_fulltext.sql
ALTER TABLE policy_documents
    ADD COLUMN IF NOT EXISTS search_tsv tsvector
    GENERATED ALWAYS AS (
        setweight(to_tsvector('simple', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('simple', coalesce(content, '')), 'B')
    ) STORED;

CREATE INDEX IF NOT EXISTS ix_policy_search_tsv
    ON policy_documents USING GIN (search_tsv);
```

启动钩子（同 Step 1.8 一起）：

```python
async def init_policy_fulltext():
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.execute(text("""
            ALTER TABLE policy_documents
            ADD COLUMN IF NOT EXISTS search_tsv tsvector
            GENERATED ALWAYS AS (
                setweight(to_tsvector('simple', coalesce(title, '')), 'A') ||
                setweight(to_tsvector('simple', coalesce(content, '')), 'B')
            ) STORED
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_policy_search_tsv
            ON policy_documents USING GIN (search_tsv)
        """))
```

### 2.7 policy_repo + policy_service

`src/repositories/policy_repo.py`：

```python
from typing import Optional, List
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.file import PolicyDocument

class PolicyRepository:
    async def create(self, db: AsyncSession, *, title, content, category, source_url, embedding, doc_metadata) -> PolicyDocument: ...
    async def list_grouped_by_source(self, db: AsyncSession) -> List[dict]:
        """GROUP BY title 聚合，返回 [{sourceFile, chunkCount}]"""
        ...
    async def count(self, db: AsyncSession) -> int: ...
    async def delete_by_title_prefix(self, db: AsyncSession, prefix: str) -> int: ...
```

`src/services/policy_service.py`：

```python
class PolicyService:
    """政策文档管理 + 入库流水线"""

    async def ingest_file(
        self,
        db: AsyncSession,
        *,
        file_content: bytes,
        filename: str,
        category: Optional[str],
    ) -> dict:
        """上传文件 → 解析 → 切块 → embedding → 入库"""
        from src.rag.file_parser import parse_file_to_text
        from src.rag.chunker import split_text
        from src.rag.embeddings import get_embeddings

        text_content = parse_file_to_text(file_content, filename)
        if not text_content.strip():
            return {"fileName": filename, "chunkCount": 0, "status": "parse_empty"}

        chunks = split_text(text_content)
        if not chunks:
            return {"fileName": filename, "chunkCount": 0, "status": "parse_empty"}

        embeddings = await get_embeddings().embed_batch([c.text for c in chunks])
        repo = PolicyRepository()
        for ch, emb in zip(chunks, embeddings):
            await repo.create(
                db,
                title=f"{filename}#{ch.index}",
                content=ch.text,
                category=category,
                source_url=filename,  # 用 filename 当 source，便于 group
                embedding=emb,
                doc_metadata={"char_start": ch.char_start, "char_end": ch.char_end},
            )
        await db.commit()
        return {"fileName": filename, "chunkCount": len(chunks), "status": "success"}

    async def list_files(self, db: AsyncSession) -> List[dict]:
        return await PolicyRepository().list_grouped_by_source(db)

    async def delete_file(self, db: AsyncSession, filename: str) -> int:
        return await PolicyRepository().delete_by_title_prefix(db, filename)

    async def search(self, db: AsyncSession, query: str, top_k: int = 5) -> List[dict]:
        from src.rag.search import hybrid_search_policy
        return await hybrid_search_policy(db, query, top_k=top_k)
```

### 2.8 policy schema `src/app/schemas/policy.py`

```python
from pydantic import BaseModel, Field
from typing import List, Optional

class PolicyUploadResponse(BaseModel):
    fileName: str
    chunkCount: int
    textLength: Optional[int] = None
    status: str  # success / parse_empty / process_failed

class PolicyFileVO(BaseModel):
    sourceFile: str
    chunkCount: int

class PolicySearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    topK: int = Field(5, ge=1, le=20)
```

### 2.9 policy 路由 `src/app/routes/policy.py`

```python
from fastapi import APIRouter, Depends, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.dependencies import get_db
from src.app import response as R
from src.app.schemas.policy import (
    PolicyUploadResponse, PolicyFileVO, PolicySearchRequest,
)
from src.services.policy_service import PolicyService

router = APIRouter(prefix="/ai/knowledge", tags=["AI 知识库"])


@router.post("/upload")
async def upload(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    result = await PolicyService().ingest_file(
        db, file_content=content,
        filename=file.filename or "unknown",
        category=None,
    )
    return R.success_resp(result)


@router.get("/list")
async def list_files(db: AsyncSession = Depends(get_db)):
    files = await PolicyService().list_files(db)
    return R.query_resp(files)


@router.get("/stats")
async def stats(db: AsyncSession = Depends(get_db)):
    files = await PolicyService().list_files(db)
    total_chunks = sum(f["chunkCount"] for f in files)
    return R.query_resp({
        "totalFiles": len(files),
        "totalChunks": total_chunks,
        "files": files,
    })


@router.delete("/{filename}")
async def delete(filename: str, db: AsyncSession = Depends(get_db)):
    n = await PolicyService().delete_file(db, filename)
    return R.success_resp(msg=f"已删除 {n} 个片段")


@router.post("/search")
async def search(req: PolicySearchRequest, db: AsyncSession = Depends(get_db)):
    results = await PolicyService().search(db, req.query, top_k=req.topK)
    return R.query_resp(results)
```

### 2.10 template_indexer

`src/rag/template_indexer.py`：

```python
"""template 语义索引 - 在 TemplateService 增删改后异步触发"""
import hashlib
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.models.template import Template
from src.models.template_embedding import TemplateEmbedding
from src.rag.embeddings import get_embeddings


def _build_index_text(template: Template) -> str:
    parts = [template.name or ""]
    if template.description:
        parts.append(template.description)
    for rule in (template.rules or []):
        parts.append(rule.name or "")
        for attr in (rule.attributes or []):
            parts.append(attr.name or "")
    return " | ".join(p for p in parts if p)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def reindex_template(db: AsyncSession, template_id: int):
    """重建单个 template 的 embedding"""
    tpl = await db.get(Template, template_id)
    if not tpl:
        return
    # 触发 lazy load rules + attributes
    _ = tpl.rules
    text_content = _build_index_text(tpl)
    if not text_content.strip():
        return
    content_hash = _hash(text_content)

    # 检查是否已存在且未变化
    existing = await db.execute(
        select(TemplateEmbedding).where(TemplateEmbedding.template_id == template_id)
    )
    existing_obj = existing.scalar_one_or_none()
    if existing_obj and existing_obj.content_hash == content_hash:
        return  # 无变化，跳过

    embedding = await get_embeddings().embed(text_content)

    if existing_obj:
        existing_obj.content_text = text_content
        existing_obj.content_hash = content_hash
        existing_obj.embedding = embedding
    else:
        db.add(TemplateEmbedding(
            template_id=template_id,
            content_text=text_content,
            content_hash=content_hash,
            embedding=embedding,
        ))
    await db.commit()
```

挂在 `TemplateService` 上：详见 [`03-agent-graph.md`](./03-agent-graph.md) 第 3.6 节。

---

## 3. 验收

```bash
# 启动后服务能跑
python main.py
# 控制台应见 "HNSW indexes created" "policy fulltext ready"

# 测试 1：上传政策文件
TOKEN="xxx"
curl -X POST http://localhost:8000/ai/knowledge/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/tmp/综测政策.pdf"
# 期望：{"code":200,"data":{"fileName":"综测政策.pdf","chunkCount":42,"status":"success"}}

# 测试 2：列表
curl http://localhost:8000/ai/knowledge/list -H "Authorization: Bearer $TOKEN"
# 期望：[{"sourceFile":"综测政策.pdf","chunkCount":42}]

# 测试 3：检索
curl -X POST http://localhost:8000/ai/knowledge/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"校三好加多少分","topK":3}'
# 期望：3 条带 score 的 policy 片段

# 测试 4：删除
curl -X DELETE "http://localhost:8000/ai/knowledge/综测政策.pdf" \
  -H "Authorization: Bearer $TOKEN"
# 期望：{"code":200,"msg":"已删除 42 个片段"}
```

---

## 4. 下一步

进入 [`03-agent-graph.md`](./03-agent-graph.md)，用 LangGraph 把意图分类 → 子图（consult / apply） → interrupt → 工具调用 → 输出 suggestions 串起来。