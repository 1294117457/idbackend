# AI Agent 方案 · 总览

> 本文是 AI Agent（智能助手 + 模板匹配引导）模块的**总目录与开发指南**。
> 整个 Agent 由 LangGraph 编排 + PostgreSQL/pgvector 向量库 + FastAPI SSE 流式接口 + Vue3 浮窗/管理端 组成。

---

## 1. 模块定位

AI Agent 解决两件事：

1. **对话咨询**：学生问"综测怎么算"、"CET-6 加多少分"这类政策性问题。Agent 通过 RAG 检索学校政策文件，LLM 生成自然语言回答。
2. **申请引导**：学生上传证明材料（或文字描述情况），Agent 自动匹配可申请的模板，结合用户已填的扩展信息（extra_info）排序 Top-N，由用户选择后跳转到申请详情 Step 2（证明材料上传）。

---

## 2. 技术选型

| 层 | 选型 | 说明 |
|----|------|------|
| LLM | 通义千问 qwen3-max（`QWEN_CHAT_MODEL`） | 兼容 OpenAI ChatCompletion 协议，支持 function_call / JSON Schema 输出 |
| Embedding | 通义千问 text-embedding-v3（`QWEN_EMBEDDING_MODEL`） | 维度 1024，可在 `pgvector` 建 HNSW 索引 |
| Agent 编排 | **LangGraph** | 用 `interrupt` 模式处理"等用户选"和"等用户上传" |
| 向量库 | **PostgreSQL + pgvector** | 复用现有 DB，避免多组件运维；HNSW 索引做余弦相似度检索 |
| LLM 调用 | LangChain `ChatOpenAI`（指向 DashScope compatible-mode） | 与 LangGraph 配套 |
| 文件解析 | `pdfplumber` + `mammoth` + `openpyxl` | requirements.txt 中已有 |
| 后端框架 | FastAPI + SSE（`StreamingResponse`） | 沿用现有架构 |
| 前端 SSE | `fetch` + `ReadableStream` | 见 `idfrontend/src/api/components/agent.ts` |
| 持久化 | 现有 `agent_session` / `agent_message` / `policy_documents` 表 + 新增 `template_embeddings` 表 | 与 `models/config.py` 等已有 ORM 一致 |

---

## 3. 整体架构图

```
┌────────────────────────────────────────────────────────────────────┐
│                          Vue3 前端                                  │
│  ┌──────────────────────┐   ┌────────────────────────────────────┐ │
│  │ ChatBubble（浮窗）     │   │ Admin KB Mgmt（管理端知识库 CRUD）    │ │
│  │ - 输入文本/上传文件     │   │ - 政策文件上传 / 列表 / 删除         │ │
│  │ - SSE 渲染 token      │   │ - 模板索引重建                     │ │
│  │ - 渲染 interrupt      │   └────────────────────────────────────┘ │
│  │   → SuggestionsCard  │                                            │
│  │   → UploadRequest    │   ┌────────────────────────────────────┐ │
│  │ - 选完跳 TemplateApply│   │ TemplateApplyDialog（已有）          │ │
│  └──────────┬───────────┘   │ - dialogStep=1 条件匹配（已有）       │ │
│             │ POST /ai/...  │ - dialogStep=2 证明材料（已有）       │ │
└─────────────┼────────────────────────────────────────────────────────┘
              │ SSE (text/event-stream)
┌─────────────▼────────────────────────────────────────────────────────┐
│                       FastAPI (agent.py 路由)                         │
│  POST /ai/agent/stream         流式对话                                │
│  POST /ai/agent/resume-stream  恢复 interrupt                          │
│  POST /ai/analyze/certificate  上传证明材料 → 候选模板                   │
│  POST /ai/analyze/generate     生成申请草稿（备用入口）                  │
│  /ai/knowledge/upload|list|delete  知识库 CRUD                          │
│  /ai/conversation/create|list|...  会话持久化                           │
└─────────────┬────────────────────────────────────────────────────────┘
              │
┌─────────────▼────────────────────────────────────────────────────────┐
│                       Agent Service 层                                │
│  AgentService                                                            │
│   ├─ invoke()        同步入口（用于非流式）                              │
│   └─ stream()        流式入口：透传到 graph.astream_events()              │
│                                                                        │
│  AgentGraph (LangGraph)                                                  │
│   ├─ classify_intent (LLM 分类 → consult/apply/other)                  │
│   ├─ consult_subgraph                                                      │
│   │   ├─ rag_retrieve                                                     │
│   │   └─ llm_answer                                                      │
│   └─ apply_subgraph                                                       │
│       ├─ gather_user_info                                                  │
│       ├─ fetch_templates                                                  │
│       ├─ [interrupt: upload_proof]   等用户上传或描述                      │
│       ├─ rag_match            混合检索（向量 + 关键词）                      │
│       ├─ llm_rank             LLM 排序 Top-N                              │
│       ├─ [interrupt: select_template]  等用户选择                          │
│       └─ redirect_to_apply    生成 frontend_payload                       │
└─────────────┬────────────────────────────────────────────────────────┘
              │
┌─────────────▼────────────────────────────────────────────────────────┐
│                        RAG & 工具层                                    │
│  ┌────────────────────────┐    ┌────────────────────────────────┐  │
│  │ RAG                    │    │ Tools (普通 Python 函数)         │  │
│  │ - chunker.py   切块     │    │ - get_user_info_tool           │  │
│  │ - embeddings.py Qwen   │    │ - get_user_scores_tool         │  │
│  │ - store.py     pgvector│    │ - get_templates_tool           │  │
│  │ - search.py    混合检索 │    │ - get_template_rules_tool      │  │
│  │ - file_parser.py OCR   │    │ - create_application_tool      │  │
│  └────────────────────────┘    │ - get_user_applications_tool   │  │
│                                └────────────────────────────────┘  │
└─────────────┬────────────────────────────────────────────────────────┘
              │
┌─────────────▼────────────────────────────────────────────────────────┐
│                    PostgreSQL + pgvector                              │
│  - users / file_metadata / template / template_category / rule /      │
│    application / proof  (既有)                                        │
│  - policy_documents     (既有 model，需补 embedding 列)                │
│  - template_embeddings  (新增：template 自身的语义索引)                 │
│  - agent_session / agent_message (会话持久化，按既有 model 补表)         │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 4. 开发分步（共 5 步）

整个 Agent 开发按依赖顺序拆成 **5 步**，每步独立可交付、可测试：

| Step | 名称 | 关键产出 | 文档 |
|------|------|---------|------|
| **Step 1** | 基础设施准备 | pgvector 扩展、policy_documents 表改造、template_embeddings 表、requirements 依赖、config 配置、文件分类枚举 | [`01-infra.md`](./01-infra.md) |
| **Step 2** | RAG 知识库搭建 | `rag/` 完整实现（chunker / embeddings / store / search / file_parser）、`policy_service` + repo + route + schema、管理端 CRUD 接口 | [`02-rag.md`](./02-rag.md) |
| **Step 3** | LangGraph Agent 实现 | 重构 `agent/` 目录（state 拆分、两个 subgraph、工具实现修正、interrupt 用法）、`agent_service` 流式接口、template 语义索引 | [`03-agent-graph.md`](./03-agent-graph.md) |
| **Step 4** | FastAPI SSE 接口与持久化 | `agent.py` / `conversation.py` / `knowledge.py` 三个路由文件、Request/Response schema、SSE 协议事件类型、会话持久化 | [`04-api-sse.md`](./04-api-sse.md) |
| **Step 5** | 前端 UI 对接 | ChatBubble 浮窗组件、SuggestionsCard 候选列表组件、UploadRequest 提示组件、与 TemplateApplyDialog 跳板集成、Admin KB 管理页 | [`05-frontend-ui.md`](./05-frontend-ui.md) |

> **依赖关系**：Step 1 → Step 2 → Step 3 → Step 4 → Step 5
> 后端必须做到 Step 4 完成才能跑通 SSE；Step 5 与 Step 3/4 可以并行（前端 mock 后端）。

---

## 5. 现有代码现状（先看清再动手）

| 模块 | 现状 | 需要做什么 |
|------|------|----------|
| `src/agent/` | 骨架已建（`builder.py`/`agent_service.py`/`state/__init__.py`），但只有 4 个简单节点，工具函数字段名错（`get_templates_tool` 用了不存在的 `template.template_name`），`submit_node`/`confirm_node` 没调 Service | **重构**：拆子图、用 LLM 分类、修正工具函数、改用 `interrupt` |
| `src/rag/` | 只有 `file_parser.py` 和 `search.py` 的 TODO 空壳 | **从零实现**：chunker / embeddings / store（pgvector） / 混合检索 / 真实 OCR |
| `src/models/file.py` | 已有 `PolicyDocument` 模型，但 `embedding` 列类型是 `String` | **升级**：`String` → `pgvector.Vector(1024)`，加 HNSW 索引 |
| `src/models/config.py` | 已有 `AgentSession`（会话持久化） | 检查是否已有 message 表，若无新增 `agent_message` |
| `src/app/schemas/template.py` | `TemplateVO` 已有 `description` 字段 | **新增** `template_embeddings` 表 / model，给 description 索引 |
| `src/app/routes/template.py` | 模板 CRUD 已完整 | **增加触发器**：`TemplateService` 增删改后异步重建索引 |
| `idfrontend/src/api/components/agent.ts` | SSE 客户端已实现 `consumeSSE`，`agentStreamChat`/`agentResumeStream` 已对接 `/ai/agent/stream` 和 `/ai/agent/resume-stream` | **复用**：只补 `onInterrupt` 处理候选列表 / 上传提示的事件 |
| `idfrontend/src/views/template/components/StepBar.vue` / `TemplateApplyDialog.vue` | StepBar 纯展示组件；Dialog 已有 `dialogStep` 状态，Step 2 处理证明材料上传 | **扩展**：Dialog 加 `prefilledSelections` / `prefilledTransforms` props，支持 agent 预填跳 Step 2 |

---

## 6. 关键设计原则（贯穿 5 步）

1. **遵守项目分层规范**（`docs/架构规范skill.md`）
   - Route 只接请求 / 调 Service / 包装 R 响应
   - ORM↔DTO 转换在 schema 层
   - DB 操作下沉到 repo / service
   - 业务异常用 `errors.py` 的通用异常，全局 handler 翻译

2. **interrupt 必须有持久化**
   - 用 `langgraph.checkpoint.postgres.PostgresSaver` 或自实现 `AgentSession` 表存 checkpoint
   - 否则前端刷新 / 切页面后会话会丢

3. **SSE 事件类型要稳定**
   - 现有前端 `AgentSSEEvent.type`：`token | interrupt | result | error | session | context_compressed`
   - 新增 1 个：`interrupt_resolved`（resume 完成后回执）
   - 不要乱加类型，前端 `consumeSSE` switch 写死

4. **不阻塞主路径**
   - 上传大 PDF 拆 2 阶段：先秒回 OCR 结果（如果走得通），再异步出 suggestions
   - 长任务用 `progress` 事件告诉前端阶段百分比

5. **不要在 agent 里直接 create_application**
   - 用户的 proofScore 是用户填的，agent 不能猜
   - Agent 只负责"告诉你该用哪个模板 + 预填哪些 attribute"，最终创建权在用户手里

6. **凭证和权限要复用现有 RBAC**
   - 所有 `/ai/*` 接口都走 `PermissionMiddleware`，新增 4 个权限码：
     - `ai:chat`（学生用）
     - `ai:knowledge:read` / `ai:knowledge:write`（管理员用）
     - `ai:config:read` / `ai:config:write`（管理员用）

---

## 7. 验收清单（5 步全部完成后）

- [ ] 学生端浮窗：
  - [ ] 输入"怎么申请校三好加分" → 走 RAG 回答（引用政策文件）
  - [ ] 上传一张"全国大学生数学建模竞赛省二等奖"证书 → agent 列出 3~5 个候选模板 → 学生选 1 个 → 跳到 `TemplateApplyDialog` Step 2（attribute 已预填）→ 学生上传证明材料 → 提交
- [ ] 管理端：
  - [ ] 上传一个 PDF 政策文件 → 自动切块 + embedding → 列表中能看到 chunk 数
  - [ ] 删除一个已上传的政策 → 学生端对话检索不到
  - [ ] 改一个模板的 description → 下次学生上传材料时能匹配到新描述
- [ ] 会话持久化：
  - [ ] 关闭浏览器再打开，能看到历史对话
  - [ ] interrupt 中断后，下次会话能恢复 thread
- [ ] 上下文压缩：
  - [ ] 长对话超过 `CONTEXT_MAX_MESSAGES` 时触发压缩，前端收到 `context_compressed` 事件

---

## 文档索引

| 文档 | 内容 |
|------|------|
| [`00-overview.md`](./00-overview.md) | 本文档：总体方案、架构图、5 步拆分、关键设计原则 |
| [`01-infra.md`](./01-infra.md) | **Step 1**：pgvector / 模型改造 / 依赖 / 配置 / 枚举 |
| [`02-rag.md`](./02-rag.md) | **Step 2**：RAG 完整实现 + 管理端 CRUD |
| [`03-agent-graph.md`](./03-agent-graph.md) | **Step 3**：LangGraph 图与节点、状态、工具 |
| [`04-api-sse.md`](./04-api-sse.md) | **Step 4**：FastAPI 路由 + schema + SSE 协议 + 会话持久化 |
| [`05-frontend-ui.md`](./05-frontend-ui.md) | **Step 5**：前端浮窗 / 候选卡片 / TemplateApplyDialog 集成 / 管理页 |