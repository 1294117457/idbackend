# 前端重构方案 v0.2

> 对应仓库 `idproject/idfrontend`(学生端)与 `idproject/idfrontend-admin`(管理端)。
> **核心结论:v0.2 起,前端零修改任务。** 本文档作为"为什么前端不需要动"的依据,以及对一些边界情况的预先约定。

---

## 0. 关键结论

| 维度 | 结论 |
|------|------|
| **是否需要重写语言** | ❌ 不需要。Vue 3 + TypeScript + Vite + Element Plus + Pinia,沿用。 |
| **是否需要重写框架** | ❌ 不需要。 |
| **是否需要重写 AI Chat 模块** | ❌ 不需要(继续走 Python 端 AI 路由)。 |
| **是否需要新加 AI 调用入口** | ⏸️ M3 阶段才需要(双链路)。 |
| **是否需要新依赖** | ❌ 不需要。 |
| **工作量** | **0 周**。本阶段不需要写前端代码,只需要确认后端接口兼容。 |

---

## 1. 现实校正(v0.1 错误假设澄清)

### 1.1 第一版假设 vs 实际

| 第一版假设 | 实际现状 |
|-----------|---------|
| 前端需要适配 Java 接口 | ❌ Python 端已经在用 `pageNum/pageSize`,跟 Java 一致 |
| AI Chat 部分需要切到 dsh-runtime | ⏸️ **本阶段不做,Python 端 LangGraph 继续工作** |
| SSE 协议需要调整 | ❌ Python 后端继续工作,**前端 SSE 调用零改** |
| 需要引入 `@microsoft/fetch-event-source` | ❌ 不需要 |
| 需要改 `vite.config.ts` proxy | ❌ 不需要,Nginx 切流即可 |
| 需要清掉 `chat.ts` 废弃文件 | ❌ 不需要,继续用 |

### 1.2 结论

**整个前端项目在 M1+M2 阶段不需要任何代码变更**。前端做的就是"继续测现有 Vue 3 代码,验收后端 API 行为一致"。

---

## 2. 我们需要做什么(只是 verification,不算开发)

### 2.1 接口兼容性验收清单(在 Java 端运行时)

跑下面的脚本/工具,**只读 Python 工程代码 + Java 工程代码 + 实际操作**,不写任何前端代码:

#### 2.1.1 响应体格式校验

```bash
# 在 Java 服务起来后,每个 controller 跑一次
curl -s http://localhost:8080/api/users/profile \
  -H "Authorization: Bearer $TOKEN" | jq

# 必须返回
# {
#   "code": 200,
#   "msg": "操作成功",
#   "data": {...}
# }
# 跟 Python 端的 ApiResponse 1:1
```

#### 2.1.2 分页参数对齐

刚刚 grep 已确认 Python 端已经在用 `pageNum/pageSize`(详见 backend.md 附录 A)。

**保险起见**:Java 端起动后,跑真实分页请求验证:
```bash
curl -s 'http://localhost:8080/api/users?pageNum=1&pageSize=10' \
  -H "Authorization: Bearer $TOKEN" | jq
```

预期:正常返回,`data.list` 和 `data.total`。

#### 2.1.3 SSE 长连接(Python 端不变)

```bash
# AI Chat 继续走 Python 8080(或者 whatever),不再切到 Java
curl -sN -X POST http://<py-host>:8000/api/ai/chat/messages/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "你好", "session_id": null}'
# 应该看到 event: content / event: done 等等
```

**结论**:前端代码里的 SSE 解析(`src/api/components/agent.ts` 已经实现)继续工作,零改。

### 2.2 Nginx 切流示意(运维侧)

Java 端和 Python 端**同时部署**,Nginx 按 URL 切流:

```nginx
location /api/auth/        { proxy_pass http://java-host:8080; }   # Java
location /api/users/       { proxy_pass http://java-host:8080; }   # Java
location /api/applications/ { proxy_pass http://java-host:8080; }  # Java
location /api/templates/   { proxy_pass http://java-host:8080; }   # Java
location /api/template-category/ { proxy_pass http://java-host:8080; }  # Java (新)
location /api/export/      { proxy_pass http://java-host:8080; }   # Java (新)
location /api/files/       { proxy_pass http://java-host:8080; }   # Java

location /api/ai/          { proxy_pass http://py-host:8000; }     # Python (保留)
location /api/embedding/   { proxy_pass http://py-host:8000; }     # Python (M2 可选切到 Java)
```

**含义**:前端发请求 → Nginx 看 URL 前缀 → 转发对应后端。**前端完全不知道也不需要知道**后端跑的是 Java 还是 Python。

---

## 3. M3 阶段(AI 部分)的前端改动(未来再说)

如果要启动 [agent.md](./agent.md) 的 M3,前端**可能**要做:

| 改动 | 工作量 | 触发条件 |
|------|--------|---------|
| AI Chat SSE 兼容 dsh 事件类型 | 1-2 天 | 当 dsh-runtime 上线后,需要把 `event: session` 这类新事件接住 |
| Tool Card / Subagent 进度条组件 | 2-3 天 | 如果 dsh 用 subagent 跑 apply,前端要渲染子任务列表 |
| 切换 dsh-runtime 的 URL | 0.5 天 | 当后端确认 dsh 协议稳定 |

**这一阶段进 M3 之前先不动前端**(M3 本身就是"AI 部分用 dsh 替换"的延期目标,跟当前 M1+M2 完全解耦)。

---

## 4. 为什么这么决定(给你 sanity check)

### 4.1 三大现实约束

1. **Python 工程不能改**(用户强约束)
2. **前端不能改**(用户强约束)
3. **Python 后端已经在用 Java 接口签名**(pageNum/pageSize、ResultVo 结构)

→ 当约束有冲突时,我们只能选**最自然的方案 = 后端切到跟前端现有签名一致的位置**。

### 4.2 1 个潜在小问题(预防针)

如果 Java 端某个 controller 行为跟 Python 不完全一致(比如权限/排序/过滤逻辑偏差),前端会发现 bug。这种情况是 **M1 阶段补足 controller** 的范畴,**不需要改前端**。

**应对**:M1 启动后第一周就是"压测对齐周",把这种 bug 集中在 Java 端修。

### 4.3 工具 / UI 行为

- 不修改 `@/api/components/*`
- 不修改 `vue-router`
- 不修改 Pinia store
- 不修改 layouts
- 不修改 `vite.config.ts`
- 不修改 `package.json`(不引入新依赖)

唯一可能调整的:`nginx.conf`(运维侧,不在前端仓库里)。

---

## 5. 双链路/Python 共享复用规则(跟前端无关但讲清楚)

### 5.1 双链路并存的好处

- 切换零停机:Nginx 切 URL 即可
- 回滚零成本:URL 切回 Python 就回滚
- 双链路互不影响:Java/Python 各自有不同的中间件实例,不共享数据库

### 5.2 双链路切换的几个阶段

| 阶段 | Java 端覆盖 | Python 端覆盖 |
|------|-----------|------------|
| **当前** | 0% | 100% |
| **M1 完成后** | 业务 CRUD(15-18 个 controller) | AI / Embedding |
| **M2 完成后** | 业务 + Embedding | AI |
| **M3 完成后** | 业务 + Embedding + AI Chat(LangGraph 不动) | 业务 |

**前端不变,前端不变,前端不变**。重要的事情说三遍。

---

## 6. 验收清单(M1+M2+前端的接口)

- [ ] 启动 Java 后端,用现有 token 调业务接口全部正常
- [ ] `/api/template-category/list` 返回的字段跟 Python 端 `template_category.py` 一致(数量、字段名)
- [ ] `/api/export/excel` 返回的 XLSX 用 Excel 打开无报错
- [ ] AI Chat `/api/ai/chat/messages/stream` 继续由 Python 处理,前端行为不变
- [ ] Embedding `/api/embedding/search` 仍可走 Python;Java 端起来后,可切到 Java,**前端零改**
- [ ] 前端任何一个页面,没有"网络错误"/"500"/"404"等
- [ ] 前端分页控件(桌面端 Vue Element Plus) 行为不变

---

## 7. 下一步

1. 你 review 这份"前端零修改"的方案,确认这是你能接受的
2. 我接下来会重点把 backend.md 和 agent.md 做完
3. 启动 M1 实施(在 `0idbackend2` 上),你只需要在浏览器手动验证
4. M1 完成后,M2 + M3 的工作都可以不涉及前端代码改动
