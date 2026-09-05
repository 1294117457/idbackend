# Java 分支重构方案(重写 v0.2)

> 本目录是 `idbackend` 仓库 java 分支对应的"Java 后端 + AI 中间件"改造方案。
> **核心原则**:不修改任何 Python 工程、不修改现有 Python 用的 PG/pgvector 中间件。Java 分支单独使用 MySQL + 独立向量库 + 独立 BM25 库,作为一条新链路。

---

## ⚡ 重要现实校正(v0.2)

第一版文档有几个**错误假设**,这是基于当前 `0idbackend2` 真实代码的校正:

| 旧假设 | 实际现状 | 影响 |
|--------|---------|------|
| "PG → MySQL 迁移" | ❌ **Java 工程已经是 MySQL**(`application.yml` 配的就是 `jdbc:mysql://...`),用 MyBatis-Plus 注解式,没有 mapper xml,**0 处 PG 痕迹** | **不需要数据迁移脚本** |
| "分页参数不一致,要改前端" | ❌ Python 端已经在用 `pageNum/pageSize`(刚验证) | **前端可以零修改** |
| "SimpleEval 算分表达式" | ❌ `ScoreCalculationService.calculate` 在 Python 端**零调用方**,纯死代码 | **直接跳过**,不补 Aviator |
| "pgvector → Qdrant" | ✅ 这部分仍然要做。**不过这是 Java 这边独立的事,跟 Python 的 pgvector 完全无关** | Java 端新加 Qdrant collection |
| "0idbackend2 已有 60% 业务" | ✅ **实际更全:16 个 controller + 36 个 mapper,基本覆盖所有业务** | 缺的不是"补业务",而是"补 AI/向量相关 + 部分缺失业务" |

**结论**:第一版文档的工作量估算全部偏大了。本次方案基于真实代码重新估算。

---

## 📚 文档索引

| 文档 | 关键变化 | 工作量估算 |
|------|---------|----------|
| **[backend.md](./backend.md)** | 基于现实(MySQL 已就位),新增 AI 中间件(Qdrant + Lucene),补 2 个缺失业务模块 | 1-2 周 |
| **[frontend.md](./frontend.md)** | **无需修改**,只需保证 AI 部分双链路(Python 和 Java)都能被前端调 | 0 周(看 + 验证) |
| **[agent.md](./agent.md)** | AI 双链路(Python 暂时保留,Java 端通过 dsh-runtime 承接) | 2-4 周(独立里程碑) |

**总规模**:2-5 周(分散到 3 个里程碑,不强求一气呵成)

---

## 🏗️ 改造后的两个并列后端(关键架构)

```
        ┌──────────────────────────────────────────────────────────────┐
        │      Browser SPA (idfrontend / idfrontend-admin,Vue 3)       │
        │      ❌ 不修改一行代码                                              │
        └───────────────────────────┬──────────────────────────────────┘
                                    │
            ┌───────────────────────┴───────────────────────┐
            │                                               │
            ▼                                               ▼
   ┌───────────────────────────┐              ┌──────────────────────────────┐
   │ idbackend (Python)         │              │ idbackend (Java  java 分支)   │
   │ 维持原状,继续工作          │              │ Spring Boot 3.2 + MyBatis-Plus│
   │                            │              │                                │
   │  - FastAPI + LangGraph     │              │  - MySQL (iddata)              │
   │  - PostgreSQL + pgvector   │              │  - Qdrant (vectors) [新]      │
   │  - Redis (existing)        │              │  - Lucene 内嵌 (BM25) [新]     │
   │  - MinIO (existing)        │              │  - Redis (新/与 Python 不冲突)│
   │                            │              │  - MinIO (新/与 Python 不冲突)│
   │ 职责:                       │              │ 职责:                          │
   │  - 业务 CRUD(/api/users..)│              │  - 业务 CRUD(/api/users..)   │
   │  - AI 对话(/api/ai/chat)   │              │  - RAG 检索(/api/embedding)  │
   │  - 嵌入检索(/api/embedding)│              │  - (AI Chat 后续由 dsh 承担)│
   │  - 文件解析、AI 模型        │              │  - 文件解析、PDF/DOCX         │
   └────┬──────────────────────┘              └─────┬──────────────────────┘
        │                                            │
        │ 仅供 Python 使用                            │ 新基础设施
        ▼                                            ▼
   ┌──────────────────────────┐              ┌─────────────────────────────┐
   │ 现有 PG 实例 (不动)      │              │ qdrant 容器 (新)            │
   │ pgvector extension(不动) │              │ iddata_mysql (新,或重用)    │
   │ 现有 Redis/MinIO(不动)   │              │ Java 实例独占 Redis/MinIO   │
   └──────────────────────────┘              └─────────────────────────────┘
```

**关键澄清**:
- **不重新搭基础设施**:不重起一份 PG、不复用 Python 的 Redis/MinIO(避免串库风险)
- **只为 Java 起新基建**:MySQL 新建或用现有的 + 新的 Qdrant 服务 + Java 进程内的 Lucene
- **前端可以同时调两套后端**:`/api/users` 可以指 Java,`/api/ai/chat` 继续指 Python,前端零改

---

## 🎯 三阶段实施计划(可独立推进)

| 阶段 | 内容 | 工作量 | 是否影响前端 |
|------|------|--------|------------|
| **M1 后端业务齐全** | `0idbackend2` 配 MySQL,补 template_category / extra_info_field / export 等 2-3 个缺失业务模块 | **1-2 周** | ❌ 前端不动 |
| **M2 向量检索 Java 化** | Java 端引入 Qdrant + 嵌入模型(复用现有 embedding service 模型下载链接),新增 `/api/embedding/*` 路由 | **2 周** | ❌ 前端不动 |
| **M3 AI Agent 升级** | Java 端的 AI Chat 用 dsh-runtime 替换(LangGraph 不动) | **2-4 周** | ⚠️ 仅 SSE 协议调整,前端**不改业务代码**,只调 tool card 组件 |

**重要**:M1/M2/M3 **完全独立**,可以按你团队节奏分开做。每个阶段对外的接口契约都不动。

---

## 🔒 强约束清单

为了不翻车,以下一律不动:

- ❌ **不动 Python 工程**:任何文件 / Docker / 中间件配置
- ❌ **不动 Python 用的 PG/pgvector/Redis/MinIO 实例**
- ❌ **不动前端任何代码**(Vue / TS / 包版本)
- ❌ **不动 Java 工程已有的 controller / service / mapper 路径**
- ✅ **Java 端可以新加包、新加 controller、新加依赖,但命名空间清晰**(放 `controller/aiController/`)

---

## 📅 M1 详细任务(business 完整化)

### M1.1 数据库(MySQL)

**Java 工程已经是 MySQL,新建/复用一份 `iddata` 数据库即可**:

```sql
-- 在 MySQL 8.x 上执行
CREATE DATABASE iddata CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'idapp'@'%' IDENTIFIED BY 'safe-password';
GRANT ALL ON iddata.* TO 'idapp'@'%';
```

应用配置(已在 `application.yml`,只需要改 host):
```yaml
spring:
  datasource:
    url: jdbc:mysql://<your-mysql-host>:3306/iddata?useSSL=false&serverTimezone=Asia/Shanghai&characterEncoding=utf8mb4
    username: idapp
    password: <safe-password>
```

### M1.2 现有 Java mapper 已覆盖情况

```
functionMapper (8):
  - LoginMapper / UserMapper / UserRoleMapper / RoleMapper / RolePermissionMapper
  - PermissionMapper / SystemConfigMapper / FieldConfigMapper

businessMapper (8):
  - ApplicationMapper / AttributeMapper / DemandApplicationMapper / DemandTemplateMapper
  - FileMapper / ProofMapper / RuleMapper / TemplateMapper

po/score (8): 全套 PO

controller: 16 个 controller (Login/User/Role/Permission/Token/Application/Template/File
            Proof/Demand/Attribute/FieldConfig/SystemConfig/McpTools)
```

**已实现业务**:`User` / `RBAC` / `Login` / `Token` / `Captcha` / `Application` / `Template` / `Proof` / `File` / `Rule` / `Attribute` / `SystemConfig` / `FieldConfig`

### M1.3 缺失业务模块(只补 2 个)

| Python 路由 | Java 状态 | M1 任务 |
|------------|----------|---------|
| `template_category.py` | ❌ 无独立 controller | **新建 `TemplateCategoryController` + Service + Mapper** |
| `export.py` | ❌ 无 controller | **新建 `ExportController` + Service**,EasyExcel 流式写 |
| `extra_info_field.py` | ⚠️ FieldConfigController 部分覆盖 | 拉差异 list,逐项补;如果实际是 FieldConfig 的子集,就跳过 |
| `score_calculation` | ❌ | **跳过(`ScoreCalculationService.calculate` 零调用方)** |
| `embedding.py` / `ai_chat.py` | ❌ | **跳过(进 M2/M3)** |

### M1.4 M1 验收

- [ ] Java 单体启动,MySQL 表自动建(MyBatis-Plus)
- [ ] 17 个业务 controller 全部跑通空接口
- [ ] 新增 `template_category` + `export` 两个 controller
- [ ] 与 Python 版的业务接口**签名 1:1 对齐**(ResponseVo 格式一致)
- [ ] 前端可以同时访问 Python(AI/Embedding)和 Java(业务),业务流程不受影响

---

## 📅 M2 详细任务(vector 化)

详见 [backend.md](./backend.md) 第 4 章。

简化版:
- 引入 Qdrant 容器(独立服务,与 PG/pgvector 完全无关)
- 新增 `EmbeddingController`,内部调 Qdrant Java SDK + embedding 模型
- 实现 BM25:Lucene 内嵌在 Java 进程,启动期一次性建索引
- 联合检索:RRF(score 融合)
- AI Chat 路由**继续指向 Python 端**,Java 端只承接 embedding 类工具

---

## 📅 M3 详细任务(AI Agent 升级)

详见 [agent.md](./agent.md)。

简化版:
- 选型 dsh(deepseek-harness),独立 microservice: `ai-gateway` + `dsh-runtime`
- MCP over SSE:Java 端补一个 `McpSseController`,dsh 通过 MCP 调 Java 后端拿数据
- SSE 协议对齐:`SessionEventNotification` ↔ 前端现有 SSE event 类型
- 前端 SSE 解析**继续走 Java 业务后端的 `/api/ai/chat/agent/*`**,Node gateway 作为透明代理

**强约束**:Python 端的 LangGraph 一行代码不改,继续工作。

---

## 🎯 你现在应该审阅的内容

1. [backend.md](./backend.md) — M1 任务清单是否准确,vector + BM25 集成方案是否接受
2. [frontend.md](./frontend.md) — 仅作为"确认前端不需要任何修改"的参考
3. [agent.md](./agent.md) — M3 任务规划是否同意 dsh 路线

确认后,我可以开始 M1 实施:在 `0idbackend2` 上开分支 `feature/m1-mysql-business-complete`,先把 MySQL 数据源激活,跑通 16 个 controller 的最小可用。
