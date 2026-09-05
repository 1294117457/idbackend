# idbackend × Prometheus × Grafana 接入指南

> 适用工程：`/home/dustp/codes/idproject/idbackend`（FastAPI + uvicorn ASGI + SQLAlchemy/Redis/LangGraph）。
> 目的：**面试准备 + 工程实操**——既能在面试里讲清原理，又能 30 分钟跑出可看的 Dashboard。
> 注意：本文档**只描述方案，不直接修改工程代码**。所有代码片段都在 `附录` 给出，等人工 Review 后再落地。

---

## 目录

| # | 文档 | 主题 |
|---|---|---|
| 0 | 本文（README） | 总览、为什么能快速接入、面试怎么讲 |
| 1 | [`01-architecture.md`](./01-architecture.md) | Prometheus / Grafana 是什么、怎么协作 |
| 2 | [`02-quickstart.md`](./02-quickstart.md) | 30 分钟跑通端到端 demo |
| 3 | [`03-code-changes.md`](./03-code-changes.md) | 工程改造清单（4 个文件 + 2 个依赖） |
| 4 | [`04-multi-worker-pitfall.md`](./04-multi-worker-pitfall.md) | 多 worker 下的指标合并坑（高频考点） |
| 5 | [`05-business-metrics.md`](./05-business-metrics.md) | DB / Redis / LLM / Agent 自定义指标 |
| 6 | [`06-grafana-dashboards.md`](./06-grafana-dashboards.md) | RED / USE / 业务 三层看板推荐 |
| 7 | [`07-interview-cheatsheet.md`](./07-interview-cheatsheet.md) | 面试 Q&A + 讲解提纲 |
| 8 | [`08-faq.md`](./08-faq.md) | 常见踩坑 |

---

## 0. 一句话回答：能，而且很合适

你这个工程是 **ASGI 框架 + 多层 Middleware + Lifespan 钩子齐全 + 多 worker** 的典型 Python 后端结构，正好命中 Prometheus + Grafana 的"标准落地形态"。**核心改动 ≈ 30 行代码、2 个 pip 依赖、4 个文件**，不侵入任何业务代码。

---

## 1. 评估：这个工程接 Prometheus 的友好度

| 工程特性 | 友好度 | 说明 |
|---|---|---|
| FastAPI（ASGI） | ⭐⭐⭐⭐⭐ | 有现成 `prometheus-fastapi-instrumentator`，或自己写 `BaseHTTPMiddleware` 也极简 |
| 中间件洋葱结构（CORS / Logging / Auth / Permission） | ⭐⭐⭐⭐⭐ | 新增 `MetricsMiddleware` 直接挂在 Logging 之后，与既有风格一致 |
| `--workers 2`（Dockerfile） | ⚠️ 必踩坑 | 多进程模式下指标会互相覆盖，必须用 `prometheus_multiproc_dir`（**这是面试加分点**） |
| SQLAlchemy 2.0 async | ⭐⭐⭐⭐ | DB 连接池 / 慢查询都能埋点 |
| Redis 缓存层 | ⭐⭐⭐⭐ | 命中率 / 延迟是天然业务指标 |
| LangGraph Agent | ⭐⭐⭐⭐⭐ | LLM token、节点耗时、工具调用频次都是高级话题 |
| Lifespan 启动钩子 | ⭐⭐⭐⭐⭐ | 启动时建 registry / 关闭时 flush，路径现成 |
| 已有 `/health` | ⭐⭐⭐ | 同理加 `/metrics` |
| JWT / RBAC / 异常处理 | 无影响 | 与指标完全解耦 |

---

## 2. 接入全景图

```
┌────────────────────────────────────────────────────────────┐
│                      Prometheus Server                       │
│   - 每 5s 主动 pull http://idbackend:8000/metrics          │
│   - 存到 TSDB，按 label 维度聚合                            │
│   - 暴露 PromQL 给 Grafana                                  │
└────────────────────┬───────────────────────────────────────┘
                     │ PromQL
                     ▼
┌────────────────────────────────────────────────────────────┐
│                         Grafana                              │
│   - 数据源 = Prometheus                                      │
│   - 三个 Dashboard：RED / USE / 业务                         │
│   - 告警规则（Alertmanager 可选）                            │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│                       idbackend (FastAPI)                    │
│                                                              │
│   Request ──► CORS ──► Logging ──► Metrics ──► Auth ──► ...  │
│                                │ (新)                        │
│                                ▼                             │
│                  MetricsMiddleware (Histogram + Counter)    │
│                  + /metrics 路由 (返回 Prometheus 文本)      │
│                                                              │
│   Lifespan: 启动 → 初始化 multiproc dir                       │
│             关闭 → 清理指标文件                                │
└────────────────────────────────────────────────────────────┘
```

---

## 3. 核心概念（面试会问）

| 概念 | 一句话 | 你工程里的对应 |
|---|---|---|
| **Metric** | 一个时间序列，可带 label | `REQ_LATENCY = Histogram(...)` |
| **Counter** | 只增不减（请求总数、错误总数） | `REQ_COUNT.labels(...).inc()` |
| **Gauge** | 瞬时值（在线人数、队列长度） | 业务用：缓存大小、连接池使用率 |
| **Histogram** | 分布（耗时 → p50/p95/p99） | `REQ_LATENCY.labels(...).observe(0.123)` |
| **Summary** | 类似 Histogram，但客户端算分位数 | 极少用 |
| **Label** | 维度标签（method/path/status） | **不要用 user_id 当 label，会爆 cardinality** |
| **Scrape** | Prometheus 主动拉取 `/metrics` | 默认 15s，开发时改 5s |
| **Pull 模型** | 服务端主动来拉，**不是**服务推 | 防火墙友好、天然聚合 |
| **TSDB** | Prometheus 自带时序库 | 7~15 天后老数据丢，可配远端存储 |

---

## 4. 30 分钟跑通（Quick Start）

> 完整步骤见 [`02-quickstart.md`](./02-quickstart.md)。这里是提纲：

### 4.1 起一个最简版
1. `pip install prometheus-client prometheus-fastapi-instrumentator`
2. 在 `main.py` 的 `FastAPI(...)` 之后加 3 行（详见 `03-code-changes.md`）
3. 启动应用，访问 `http://localhost:8000/metrics` —— **应该已经能看到指标了**

### 4.2 起 Prometheus
```bash
docker run -d -p 9090:9090 \
  -v $(pwd)/observability/prometheus.yml:/etc/prometheus/prometheus.yml \
  prom/prometheus
```
访问 `http://localhost:9090`，搜 `http_requests_total` —— 有数据就算通。

### 4.3 起 Grafana
```bash
docker run -d -p 3000:3000 grafana/grafana
```
访问 `http://localhost:3000`（admin/admin），加 Prometheus 数据源 → `http://host.docker.internal:9090`，导入 Dashboard ID `16110`（FastAPI 官方模板）即可。

### 4.4 看 Dashboard
- RED：Rate（QPS）、Errors（4xx/5xx 比例）、Duration（p95/p99）
- USE：CPU、内存、DB 连接池、Redis 连接
- 业务：AI Chat 调用次数、模板调用 TopN、申请提交成功率

---

## 5. 面试讲解提纲（5~8 分钟版）

**开场（30s）**：
> "Prometheus 是 CNCF 毕业的时间序列数据库 + 监控系统，Grafana 是可视化层。两者通过 PromQL 解耦——Prometheus 存数据，Grafana 画图。"

**原理（2 分钟）**：
- Pull 模型 vs Push 模型（为什么不用 StatsD）
- Metric 类型四件套：Counter / Gauge / Histogram / Summary
- Label 维度的 cardinality 问题
- TSDB 的 chunk + WAL 机制（一句话带过）

**工程实践（3 分钟）**：
- ASGI Middleware 注入点
- 多 worker 的 `prometheus_multiproc_dir` 坑
- RED 方法 / USE 方法
- Histogram bucket 选择（**这是个高频考点**：默认桶对 web 请求不合适）

**业务指标（2 分钟）**：
- 数据库：连接池使用率、慢查询计数
- Redis：命中率、p99 延迟
- LLM：token 消耗、单次调用成本、节点耗时（LangGraph 节点埋点）

**反模式 & 陷阱（1 分钟）**：
- ❌ 把 user_id / email 当 label（cardinality 爆炸）
- ❌ 用 Gauge 统计总请求数（重启就丢）
- ❌ 业务关键路径 `try/except` 吞异常但不上报
- ❌ 单实例 Gauge 跨多 worker（要 `multiprocess_mode`）

---

## 6. 不动代码也能讲清的部分

如果你时间紧、只想面试过，**以下 6 个点不需要改工程也能讲**：

1. **Pull 模型**：Prometheus 主动来拉，对防火墙友好
2. **RED**：Rate / Errors / Duration——任何 HTTP 服务都适用
3. **Histogram bucket**：默认 `[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10]`，对应 web 请求的 p99 在几十 ms ~ 几百 ms
4. **Cardinality**：label 组合数 = 各维度取值数相乘，超过 10000 就要警惕
5. **多进程**：每个 worker 写自己的 mmap 文件，Prometheus 抓的时候 `merge` 起来
6. **告警分级**：warning（人工看）、critical（PagerDuty 拉人）

---

## 7. 推荐落地顺序

| 阶段 | 时间 | 内容 | 价值 |
|---|---|---|---|
| **P0** | 30 min | 自动埋点（`prometheus-fastapi-instrumentator`）+ 单进程跑通 | **面试够用** |
| **P1** | 1 hour | 多 worker 修复 + docker-compose 起 Prometheus/Grafana | 可演示 |
| **P2** | 2 hours | 自定义业务指标（DB/Redis/LLM） | 加分项 |
| **P3** | 4 hours | 告警规则 + Dashboard 模板化 | 进阶 |
| **P4** | 1 day | Alertmanager + 远端存储 + 长期归档 | 生产级 |

---

## 8. 后续步骤

1. 先 Review 本目录下 8 个文档
2. 确认接入范围（P0 即可，还是直接 P2）
3. 切到 Agent 模式，我按 `03-code-changes.md` 的清单一次性落地
4. 起 Prometheus + Grafana，导入 Dashboard

---

## 附录：术语速查

- **RED 方法**：Rate（请求速率）、Errors（错误率）、Duration（耗时）——面向服务
- **USE 方法**：Utilization（使用率）、Saturation（饱和度）、Errors（错误）——面向资源
- **Cardinality**：label 组合的笛卡尔积数量级
- **Scrape interval**：Prometheus 抓取间隔，开发 5s、生产 15s~30s
- **Recording rules**：PromQL 预聚合（高频查询加速）
- **Alerting rules**：阈值告警 → Alertmanager → 邮件/钉钉/企微
