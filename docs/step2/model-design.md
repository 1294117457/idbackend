# 向量表模型设计

## 概述

本项目使用 **pgvector** 作为向量数据库（PostgreSQL 扩展），设计**一张统一向量表**：

| 表名 | 用途 | 管理方式 |
|------|------|----------|
| `embeddings` | 统一向量 | 后台管理手动上传/删除 |

表使用 `pgvector` 的 `Vector(1024)` 类型存储 1024 维 embedding 向量。

---

## 1. Embedding（统一向量）

### 用途

存储所有知识库内容的语义向量，供 Agent RAG 检索使用。

通过 `category` 字段区分不同业务类型：
- POLICY：政策文件
- SYSTEM_GUIDE：系统介绍文档
- TEMPLATE：模板（关联 Template 表）

### 字段设计

| 字段名 | 类型 | 可空 | 说明 |
|--------|------|------|------|
| `id` | Integer | 否 | 主键 |
| `title` | String(200) | 可 | 标题（方便人类识别） |
| `content` | String | 否 | 内容原文（检索后展示用） |
| `category` | String(50) | 否 | 业务类型：POLICY / SYSTEM_GUIDE / TEMPLATE |
| `ref_id` | Integer | 可 | 关联业务 ID（如 template.id） |
| `embedding` | Vector(1024) | 可 | Qwen text-embedding-v3 向量 |
| `created_at` | DateTime | 否 | 创建时间 |
| `updated_at` | DateTime | 否 | 更新时间 |

### 索引

- `idx_category`: `category` 字段索引
- `idx_ref_id`: `ref_id` 字段索引（快速定位关联记录）
- `idx_hnsw_embedding`: HNSW 向量索引（启动时创建）

### Category 枚举

```python
class EmbeddingCategory(str, enum.Enum):
    """向量类型"""
    POLICY = "POLICY"              # 政策文件
    SYSTEM_GUIDE = "SYSTEM_GUIDE"  # 系统介绍文档
    TEMPLATE = "TEMPLATE"         # 模板
    FAQ = "FAQ"                    # 常见问题（未来扩展）
```

---

## 2. 向量检索流程

### 2.1 存入流程

```
原始文档 / 模板
    ↓
解析成纯文本（PDF → txt, Word → txt 等）
    ↓
文本切块（chunk）  ← 按配置大小切割，如 500 字符一块，50 字符重叠
    ↓
调用 embedding API  ← Qwen text-embedding-v3
    ↓
生成向量 [0.123, -0.456, ...]  ← 1024 维浮点数数组
    ↓
存入 pgvector  ← content + embedding + category 一起存储
```

### 2.2 检索流程

```
用户问题
    ↓
LLM 意图分类（轻量 prompt）→ 确定 category
    ↓
向量检索（WHERE category = ?）
    ↓
返回匹配的内容
```

### 2.3 意图分类示例

| 用户问题 | 意图 | category | 检索范围 |
|----------|------|----------|----------|
| 系统怎么登录 | system_usage | SYSTEM_GUIDE | 仅系统文档 |
| 数学竞赛能加多少分 | policy_query | POLICY | 仅政策文件 |
| 有什么奖学金可以申请 | application_query | TEMPLATE + POLICY | 模板 + 政策 |
| 什么是综合测评 | general_query | 无 | 全量检索 |

### 2.4 优势

- **节省 token**：只召回相关类型文档
- **提高精度**：减少无关内容干扰
- **灵活扩展**：新增类型只需加 category 值

---

## 3. Template CRUD 联动

模板的向量需要与 Template CRUD 联动维护。

### 联动策略

在 `TemplateService` 中调用向量服务：

```python
# TemplateService
async def create_template(self, data: CreateTemplate):
    # 1. 创建模板
    template = await self.repo.create(data)

    # 2. 生成向量
    await self.vector_service.upsert(
        content=template.name + " " + template.description,
        category="TEMPLATE",
        ref_id=template.id,
    )
    return template

async def update_template(self, template_id: int, data: UpdateTemplate):
    # 1. 更新模板
    template = await self.repo.update(template_id, data)

    # 2. 检查内容是否变化，变化则重建向量
    if self._content_changed(template_id, new_content):
        await self.vector_service.upsert(...)

    return template

async def delete_template(self, template_id: int):
    # 1. 删除向量
    await self.vector_service.delete(ref_id=template_id)

    # 2. 删除模板
    await self.repo.delete(template_id)
```

### 联动方式对比

| 方式 | 适用场景 |
|------|----------|
| Service 层调用 | ✅ 推荐，本项目规模刚好 |
| SQLAlchemy 事件 | 跨模块隐式调用，调试复杂 |
| 信号量/中间件 | 实现复杂，不适合此场景 |

---

## 4. 向量索引（HNSW）

`embedding` 字段需要创建 HNSW 索引，启动时执行：

```sql
CREATE INDEX IF NOT EXISTS ix_knowledge_embedding_hnsw
ON embeddings
USING hnsw (embedding vector_cosine_ops);
```

**注意**：
- 使用余弦距离 `vector_cosine_ops` 作为度量
- `create_all()` 无法自动创建 HNSW 索引，必须用 raw SQL
- 索引创建是幂等的，多次执行不会报错

---

## 5. 数据量分析

### 预估规模

| 数据类型 | 数量 | 每条 chunk 数 | 总向量条数 |
|----------|------|--------------|------------|
| 模板 | 100-1000 个 | 1-3 个 | ~2000 |
| 政策文件 | 50-200 篇 | 5-20 个 | ~2000 |
| 系统文档 | 10-50 篇 | 3-10 个 | ~300 |
| **总计** | - | - | **~5000** |

### 性能参考

| 数据量 | HNSW 索引 | 查询延迟 |
|--------|-----------|----------|
| 10 万条 | ✅ | < 10ms |
| 100 万条 | ✅ | < 50ms |
| 1000 万条 | ✅ | < 200ms |

**结论：5000 条数据量完全不需要分表，一张表足够。**

---

## 6. 模型文件

| 文件 | 说明 |
|------|------|
| `src/models/embedding.py` | Embedding 模型 |
| `src/models/__init__.py` | 导出模型 |

---

## 7. 配置项

向量相关配置放在 `src/infra/config.py`：

```python
# LLM
QWEN_EMBEDDING_MODEL: str = "text-embedding-v3"

# RAG / 向量
QWEN_EMBEDDING_DIM: int = 1024          # 向量维度
RAG_CHUNK_SIZE: int = 500                # 文本切块大小（字符数）
RAG_CHUNK_OVERLAP: int = 50             # 切块重叠大小
RAG_TOP_K_VECTOR: int = 10              # 向量检索召回数
RAG_TOP_K_KEYWORD: int = 6              # 关键词检索召回数
RAG_TOP_K_FINAL: int = 5                # 最终返回数
RAG_RRF_K: int = 60                     # RRF 融合参数
```

---

## 8. 与现有系统的关系

```
Template（模板）
└── 创建/更新/删除时 → 自动触发向量同步（ref_id = template.id）

Agent RAG 检索
├── category="SYSTEM_GUIDE" → 召回系统文档
├── category="POLICY"        → 召回政策文件
├── category="TEMPLATE"     → 召回模板
└── 无过滤                  → 全量召回
```
