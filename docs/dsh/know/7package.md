## 全部包分 6 大类

### 1. 组装与配置（你的入口）

| 组             | 干什么                                                      |
| :------------- | :---------------------------------------------------------- |
| `bundle/`      | ★ 配置文件 cordis.patch.yml 所在地（base/web-app/headless） |
| `boot/`        | 启动引导逻辑                                                |
| `preset/`      | Agent 预设（标准/PTC/极简/创造）                            |
| `settings/`    | 用户设置的读写                                              |
| `credentials/` | API Key 等凭证管理                                          |
| `storage/`     | 非会话的通用持久化                                          |
| `workspace/`   | 工作区实体                                                  |

------

### 2. Agent 核心（后端大脑）

| 组               | 干什么                                                     |
| :--------------- | :--------------------------------------------------------- |
| `core/`          | ★ Agent 脊柱：会话、提示词、工具注册、Agent 接口、循环驱动 |
| `llm/`           | ★ 模型调用（DeepSeek/OpenAI 适配器）                       |
| `compaction/`    | 上下文压缩                                                 |
| `context/`       | 注入请求上下文（时间、workspace 指令等）                   |
| `session/`       | 会话持久化（JSONL/SQLite）                                 |
| `session-query/` | 会话检索/搜索                                              |
| `goal/`          | 目标管理                                                   |
| `plan/`          | Plan 模式                                                  |
| `guard/`         | 循环保护（防重复调用、超时）                               |
| `schedule/`      | 定时任务                                                   |

------

### 3. Agent 能力/工具（后端手脚）

| 组              | 干什么                         |
| :-------------- | :----------------------------- |
| `fs/`           | 文件读写                       |
| `shell/`        | Bash 命令执行                  |
| `terminal/`     | 持久终端（PTY）                |
| `subprocess/`   | 进程管理                       |
| `sandbox/`      | 沙箱隔离（限制权限）           |
| `code-runtime/` | 代码执行（worker 线程）        |
| `lsp/`          | 语言服务器（代码智能）         |
| `web/`          | 网页搜索/抓取                  |
| `todo/`         | 任务清单工具                   |
| `skill/`        | 技能加载                       |
| `subagent/`     | 子 Agent 委托                  |
| `jobs/`         | 后台任务                       |
| `workflow/`     | 工作流引擎                     |
| `attachment/`   | 附件管理                       |
| `spill/`        | 大输出裁剪                     |
| `extensions/`   | 运行时自修改（Agent 装卸插件） |

------

### 4. 前端 UI（浏览器端）

| 组        | 干什么                                                       |
| :-------- | :----------------------------------------------------------- |
| `client/` | ★ 所有 `ui-*` 浏览器插件 + 基础设施（slot、runtime、connection） |
| `host/`   | Web 服务器（给前端提供 HTTP/SSE）                            |

------

### 5. 外部对接

| 组             | 干什么                              |
| :------------- | :---------------------------------- |
| `sdk/`         | JSON-RPC SDK（外部程序调 dsh）      |
| `acp/`         | Agent Client Protocol（自动化接入） |
| `api/`         | RPC 网关                            |
| `typert/`      | 类型生成                            |
| `hooks/`       | Claude Code / Codex 协议兼容桥      |
| `interaction/` | 人机协作（审批、权限、ask-user）    |
| `feedback/`    | 人类反馈                            |
| `identity/`    | 匿名身份                            |
| `e2b/`         | E2B 远程沙箱（POC）                 |

------

### 6. 支撑（开发者用）

| 组              | 干什么       |
| :-------------- | :----------- |
| `examples/`     | 示例         |
| `test-support/` | 测试基础设施 |
| `util/`         | 工具函数     |

------

## 你关注的重点

如果你要基于 dsh 做自己的 Agent 应用：

必看：bundle/（配置入口）+ core/（Agent 怎么转）+ llm/（模型怎么调）

按需看：client/（改 UI）、fs/shell/web（用什么工具）、preset/（工作模式）

不用管：test-support/、util/、typert/、examples/