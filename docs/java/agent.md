# Agent 重构方案 v0.2

> 对应跨后端版本的 AI 编排层。Python 端的 LangGraph **一行不改、继续工作**;Java 端通过引入 `dsh-runtime`(独立 microservice)逐步取代 AI Chat 的 Python 实现。
> **核心结论**:M3 阶段(M1/M2 完成后),Java 端用 deepseek-harness 重构 AI Chat 编排,与 Python 端的 LangGraph 双链路并存,前端无感切流。

---

## 0. 关键结论

| 维度 | 结论 |
|------|------|
| **是否复用 LangGraph(Python)** | ✅ 保留,Python 端**一行代码不改**继续工作 |
| **是否引入 dsh(Java 端 AI)** | ⏸️ M3 阶段,M1+M2 不做 |
| **MCP 协议** | dsh 通过 MCP over SSE 调 Java 后端 |
| **工作量** | **M3 独立里程碑,2-4 周(1 个 TS 熟手)** |
| **M1+M2 涉及本方案吗** | ❌ **M1+M2 完全跟 agent 无关**(按用户强约束:不动 Python、不做 AI),该阶段不读本文档 |

---

## 1. M3 是可选的独立目标

```
M1: Java 业务后台齐全         ─┐
M2: Java 端 embedding/向量  ─┤ 跟 agent 完全解耦,互不影响
M3: Java 端接 dsh-runtime  ─┘  本文档详细描述
```

**为什么 M3 独立**:
1. 用户强约束"不动 Python",意味着 LangGraph 一直跑着,不能废
2. dsh-runtime 是独立的 Node.js microservice,跟 Java/Python 都解耦
3. dsh 通过 MCP 协议调 Java 端的数据接口,**不影响业务代码**

**何时启动 M3**:
- M1+M2 完成后,Java 已经能独立撑业务
- 你对 AI 部分有进一步诉求(多工具、更长对话、subagent 等)
- 团队有 TS 能力

---

## 2. 与 Python LangGraph 共存的架构

```
        ┌────────────────────────────────────────────────────────────┐
        │         Browser SPA (idfrontend/admin,Vue 3,零改)         │
        └────────────────────────┬───────────────────────────────────┘
                                 │ HTTP + SSE (frontend不知道谁在响应)
                                 │
                       Nginx 路由分发
                                 │
              ┌──────────────────┴──────────────────┐
              │ /api/ai/**                         /api/embedding/**
              ▼                                     ▼
   ┌─────────────────────────┐           ┌─────────────────────────┐
   │ Python idbackend (保留)  │           │ Java idbackend (M2 完成) │
   │  - FastAPI              │           │  - Spring Boot 3.2      │
   │  - LangGraph            │           │  - MySQL                │
   │  - PG + pgvector         │           │  - Qdrant + Lucene     │
   │  - /api/ai/chat/stream  │           │  - /api/embedding/*      │
   └─────────────────────────┘           └─────────────────────────┘
              │                                     │
              │                                     │ MCP over SSE
              │                                     ▼
              │                           ┌──────────────────────────┐
              │                           │ dsh-runtime              │
              │                           │ (Node.js microservice)   │
              │                           │ - deepseek-harness 18包  │
              │                           │ - skill/preset/plan     │
              │                           │ - subagent/interaction │
              │                           └──────────────────────────┘
              │                                     │
              │                                     │ DeepSeek API
              │                                     ▼
              │                           ┌──────────────────────────┐
              │                           │ LLM (DeepSeek / 智谱)     │
              │                           └──────────────────────────┘
              │
              │ Direct HTTP(SSE)+api/ai/chat/stream
              ▼
       前端 SSE 协议就跟现有 agent.ts 一致
       (token / done / error / apply_pending)
```

**关键**:M3 上线后,**两个 AI 链路并存**:
- Python 链路:用 LangGraph,继续工作
- Java 链路:用 dsh-runtime,**通过 SSE 暴露同一种前端协议**

前端代码完全不知道;Nginx 切到哪个就调哪个。

---

## 3. M3 任务详述

### 3.1 引入 dsh-runtime

**新建独立 microservice**(Node.js,不跟 Java 进程混):

```
idbackend-microservices/
├── ai-gateway/                # HTTP↔stdio JSON-RPC 桥
├── dsh-runtime/               # dsh 进程,长跑
├── docker-compose.yml
└── README.md
```

引入方式(参考 [agent.md v0.1](...)):`dsh-runtime` 用 pnpm 引入 `deepseek-harness` 18 个精选包(cordis / core / llm-deepseek / mcp-client / session / skill / plan / preset / compaction / interaction / subagent / web / guard / util 等)。

### 3.2 鉴权策略(双链路一致)

**dsh-runtime 不需要直接处理 JWT**——它在 ai-gateway 后面,ai-gateway 负责 JWT 校验,dsh 只负责 AI 编排。

> ⚠️ **不要求 Python 端改 JWT secret**。Java 端生成自己的 JWT,前端访问 Java 链路时用 Java 的 token,前端访问 Python 链路时用 Python 的 token。ai-gateway 只验证前端发来的 token 是否合法,不跨端复用。

### 3.3 MCP 协议(Java 端补 SSE 入口)

Java 端新增一个 controller:

```java
// controller/mcp/McpSseController.java
@RestController
@RequestMapping("/internal/mcp")
public class McpSseController {
    @GetMapping(value = "/sse", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter connect() {
        SseEmitter emitter = new SseEmitter(-1L);
        // 接收 dsh 客户端的 MCP 连接
        // 推荐用 io.modelcontextprotocol.sdk:mcp-server-webmvc-sse
        return emitter;
    }

    @PostMapping("/messages")
    public ResponseEntity<Void> dispatch(@RequestBody String body) {
        // dsh 的 JSON-RPC 请求体
        // 用 Java 端的 Service/Mapper 执行 tool call
        // 把结果通过 SSE 推回 dsh
        return ResponseEntity.accepted().build();
    }
}
```

或更省心:**直接引入 `io.modelcontextprotocol.sdk:mcp-server-webmvc-sse`**,自动生成符合 MCP 协议的 endpoint。

MCP 调 Java 后端的 tool 包括但不限于:
- `get_user_info(userId)` → users + user_role 表
- `get_score_templates(categoryId)` → template 表
- `submit_application(payload)` → application 表
- `upload_proof(fileId)` → file 表
- `search_documents(query)` → M2 阶段 Java 端的 embedding.search()

每个 tool 对应 Java 后端一个 service method。

### 3.4 SSE 协议对齐(关键设计点)

dsh 的 wire protocol 已经设计了**5 类事件**,刚好覆盖现有前端 SSE event:

| dsh wire event | 前端 SSE event | 含义 |
|--------------|---------------|------|
| `session.event` | `content` | 增量 token 流 |
| `session.event` | `session` | 会话元数据 |
| `session.status` (running → idle) | `done` | 结束 |
| `session.status` (idle → running) | (前端忽略) | 重启信号 |
| `subagent.started` | `apply_pending` | 子任务开始 |
| `subagent.finished` | `done`(配合 useId 校验) | 子任务结束 |

**ai-gateway 就是个 SSE 转发器**:
```typescript
// ai-gateway/src/stream.ts
async function* mapDshToFrontend(stream: AsyncIterable<DshEvent>): AsyncIterable<FrontendEvent> {
  for await (const evt of stream) {
    switch (evt.event.type) {
      case 'session.event':
        if (evt.event.envelope.type === 'message.user' /* ... */) {
          yield { event: 'session', data: {...} }
        }
        if (evt.event.envelope.type === 'content.partial') {
          yield { event: 'content', data: { content: evt.event.envelope.text } }
        }
        break
      case 'session.status':
        if (evt.status === 'idle') yield { event: 'done', data: {...} }
        break
      case 'subagent.started':
        yield { event: 'apply_pending', data: {...} }
        break
      // ...
    }
  }
}
```

→ ai-gateway 暴露的 SSE 协议**跟现在 Python 后端的 SSE 一致**。

### 3.5 双链路切流策略

Nginx 切到 Java 端:

```nginx
# M3 上线前
location /api/ai/chat/ { proxy_pass http://py-host:8000; }

# M3 上线后,先 10% 流量切到 Java,观察无问题再 50%、100%
location /api/ai/chat/ {
    proxy_pass http://ai-gateway-host:3001;  # Java 的 ai-gateway,内部分流
}

# AI Gateway 内部:
#   - 90% → Python idbackend (LangGraph, 完全不动)
#   - 10% → dsh-runtime (Java 端,验证 dsh 协议)
```

### 3.6 M3 验收

- [ ] dsh-runtime 起来,stdio JSON-RPC OK
- [ ] ai-gateway 把 dsh 的 wire event 转成前端 SSE event,跟 Python 完全一致
- [ ] Java 后端新增 `McpSseController`,dsh 能通过 MCP 调 Java 的 user/template/file 等 service
- [ ] 前端代码零修改,AI Chat 仍然正常
- [ ] 切流 10% → 50% → 100%,无 P0/P1 故障
- [ ] dsh 版本回退时,100% 切回 Python,前端零感知

---

## 4. LangGraph vs dsh 选型对比(再讲一次)

| 维度 | LangGraph(Python) | dsh(Java / Node 端) |
|------|------------------|-------------------|
| 节点编排 | StateGraph 自带 | cordis plugin + preset |
| MCP client | ❌ 无 | ✅ `mcp-client` 完整 |
| Subagent | 需自研 | ✅ `subagent/` + `SubagentFinishedNotification` |
| Session 持久化 | 自实现 | ✅ SQLite 内置 `dsh-session` |
| Compaction | 需自研 | ✅ `compaction/` 内置 |
| 多 provider | 自接 | ✅ `llm-deepseek` + `llm-pi-ai` |
| TS/Python SDK | Python | ✅ `@deepseek-ai/dsh-sdk-client` + `python/sdk` |
| 生产经验 | 大量 | DeepSeek 内部生产 |

**结论**:如果你的 LangGraph 实现简单(20+ 文件规模),M3 阶段切换到 dsh 是有意义的工作量(2-4 周)。如果 LangGraph 已经很复杂且满足需求,可以**永久保留 Python 链路,M3 不上**。

---

## 5. 强约束清单(对 M3 仍然适用)

- ❌ **Python 工程不改**:LangGraph 永远在,不要求 dsh 替换它
- ❌ **Python 中间件不动**:PG/pgvector 永远独立
- ❌ **Java 工程已有路径不动**:只在 `controller/aiController/` 和 `controller/mcp/` 新加
- ❌ **前端不改**:M3 上线时前端代码**零修改**

如果发现 M3 任务里需要改前端或 Python → 说明设计有误,要回头调方案。

---

## 6. M3 时间表(独立项目,不在 M1+M2 范围)

| 周次 | 内容 |
|------|------|
| W1 | dsh 工程调研:`examples/jsonrpc-agent` 跑通 + 18 个精选包引入 + `cordis.yml` 最小骨架 |
| W2 | 4 类 prompt 翻译(consult/router/apply/chat) + 注册成 dsh skill/preset |
| W3 | Java 端补 McpSseController(MCP over SSE)+ dsh 通过 MCP 调 Java user/template/file service |
| W4 | ai-gateway 实现 SSE bridge;前端联调;切流 10% → 50% → 100% |
| **合计** | **4 周,1 个 TS 熟手**;可与 M1/M2 并行启动,**完全独立项目** |

---

## 7. 与本目录其他文档的边界

| 边界 | 归属 |
|------|------|
| **业务 CRUD / RBAC / 模板管理** | backend.md |
| **Qdrant + Lucene embedding 检索** | backend.md |
| **AI Chat(会话流式回复)** | agent.md (M3) |
| **MCP tool server(Java 端补)** | backend.md + agent.md 共管 |
| **Python LangGraph 维持** | 不归本文档管,Python 工程自己负责 |
| **dsh-runtime 进程** | agent.md (M3) |
| **ai-gateway** | agent.md (M3) |

**M1+M2 阶段,agent.md 不需要阅读**。

---

## 8. 下一步

1. 你 review v0.2,确认 M3 的边界(M3 可选,不强求启动)
2. 如果暂时不做 M3,项目就在 M1+M2 收尾,完整路径约 4 周
3. 如果要做 M3,届时跟我要 dsh-runtime / ai-gateway 的工程骨架

> 注:用户提交"暂时不修改代码,先审文档"的任务,本文档满足。
