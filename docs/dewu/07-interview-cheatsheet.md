# 07 · 面试 Q&A & 讲解提纲

> 准备 8 个核心问题，每个给出**标准答案 + 你工程里的具体例子**，方便临场发挥。

---

## Q1：Prometheus 和传统监控（Zabbix / Nagios）有什么区别？

**标准答案**：

| 维度 | Zabbix/Nagios | Prometheus |
|---|---|---|
| 数据模型 | 指标 + 主机二维 | 多维 label 时间序列 |
| 采集 | Agent 推 + 周期探测 | Pull 模型主动抓 |
| 存储 | 关系型数据库 | 自研 TSDB（更便宜、更快） |
| 适用场景 | 传统主机、网络设备 | 云原生、动态服务 |
| 查询 | 自有 DSL | PromQL（更强大） |
| 服务发现 | 手动配置 | K8s SD / Consul / 文件 |

**结合你工程**：
> "我这个后端是容器化部署（Dockerfile + docker-compose），服务发现需求强，所以选 Prometheus。它对短生命周期容器友好——容器销毁时 series 自然消失，不需要手动 cleanup。"

---

## Q2：Prometheus 的 Pull 模型有什么好处？

**标准答案**（三个核心点）：

1. **失败检测与服务发现复用同一机制**
   - 抓不到 → 服务挂了 / 下线了 → 一举两得
2. **单向网络，出方向即可**
   - 不需要开入站端口，对防火墙/NAT 友好
3. **服务端控制抓取节奏**
   - 防止客户端乱推导致 OOM

**反方观点（主动说，显深度）**：
> "Pull 模型对短任务（CI 跑一次就跑完）不友好，需要 Pushgateway 做中转。Prometheus 官方给的建议是'尽量用 sidecar + Pull'。"

---

## Q3：什么是 Cardinality？为什么重要？

**标准答案**：
- Cardinality = 标签值的笛卡尔积
- `http_requests_total{method, path, status}` → 假设 5 methods × 50 paths × 5 status = 1250 series（合理）
- `http_requests_total{method, path, status, user_id}` → 1250 × 100万 user = 12.5 亿 series（爆炸）

**为什么重要**：
- 每个 series 都要存 mmap 文件
- 抓取 / 聚合都要遍历所有 series
- 10000 series 是经验上限

**你的工程该怎么避免**：
> "我监控 HTTP 请求会用 route template（如 `/api/users/{user_id}`）而不是真实路径，绝不把 user_id 当 label。"

---

## Q4：Counter / Gauge / Histogram / Summary 的区别？

**标准答案**：

| 类型 | 语义 | 典型场景 | 多进程 |
|---|---|---|---|
| Counter | 只增不减 | 请求数、错误数 | 自动求和 |
| Gauge | 瞬时值 | CPU、连接池、队列长度 | 需 `multiprocess_mode` |
| Histogram | 分布，可算分位数 | 耗时、响应大小 | 自动求和 |
| Summary | 客户端算分位数 | - | **不支持** |

**关键差异**：Histogram 算的是**近似**分位数（基于 bucket 线性插值），Summary 是**精确**的但不能跨实例聚合。生产**基本都用 Histogram**。

---

## Q5：什么是 Histogram 的 Bucket？怎么选？

**标准答案**：
- Bucket = 把样本分到几个区间（`le="0.1"` 表示 ≤ 100ms 的样本数）
- 默认桶：`.005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5, 10`
- 选桶原则：**覆盖你服务的实际耗时范围**（不要太细，不要太粗）

**反模式**：
> ❌ 默认桶对 RPC 调用合适，对 API Gateway 不够（可能 p99 在 50ms 以下，第一个桶就满了）
> ❌ 为了"精确"加 100 个桶（cardinality 爆炸）

**实战**：
```python
Histogram(
    "http_request_duration_seconds",
    ...,
    buckets=(0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0)  # 自己调
)
```

---

## Q6：多实例（多 worker / K8s Pod）下怎么采集？

**标准答案**：

| 部署形态 | 解决方案 |
|---|---|
| 单进程 | 默认 in-memory，啥都不用做 |
| 多 worker（uvicorn --workers 4） | `PROMETHEUS_MULTIPROC_DIR` + mmap |
| K8s 多 Pod | 每个 Pod 独立采集 + Prometheus ServiceMonitor 做服务发现 |
| 短任务 | Pushgateway 中转 |

**你的工程**（Dockerfile 启动 `workers=2`）：
> "我用 `PROMETHEUS_MULTIPROC_DIR=/tmp/prom_multiproc` 环境变量，prometheus_client 自动切到 mmap 模式，每个 worker 写自己的指标文件，`/metrics` 端点通过 `MultiProcessCollector` 聚合。"

---

## Q7：RED 和 USE 方法分别是什么？什么时候用？

**RED（面向服务）**：
- **R**ate：每秒请求数
- **E**rrors：错误率
- **D**uration：耗时（p95/p99）

**USE（面向资源）**：
- **U**tilization：使用率（CPU、内存、连接池）
- **S**aturation：饱和度（队列长度、等待时间）
- **E**rrors：错误事件数

**你的工程怎么用**：
> "RED 用来监控业务层——'应用现在表现怎么样'。USE 用来监控基础设施——'机器、连接池、磁盘是不是快撑不住了'。两个 Dashboard 各管一摊。"

---

## Q8：Prometheus 怎么做告警？

**标准答案**：

1. **告警规则**（PromQL 表达式 + 阈值 + 持续时间）
   ```yaml
   - alert: HighErrorRate
     expr: sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m])) > 0.05
     for: 2m                       # 持续 2 分钟才触发
     labels: {severity: critical}
     annotations: {summary: "..."}
   ```

2. **Alertmanager** 负责：
   - 去重（同一个告警多个实例）
   - 分组（按 service / alertname）
   - 抑制（critical 触发时抑制 warning）
   - 路由（钉钉、企微、PagerDuty）

3. **Prometheus 推 → Alertmanager → 通知渠道**

**面试加分点**：
> "告警的难点不是'配规则'，是'避免告警疲劳'。生产经验是：**一个服务最多 5~10 条核心告警**，每条都要有明确 owner 和 runbook。"

---

## 进阶题（聊深入了用）

### Q9：Prometheus 的存储原理？

**一句话**：
> 每个 metric 一个目录，每个 series 一个文件，append-only 写 + 周期性压缩（每 2 小时 merge 成 block）。内存里维护 index 加速查询。

### Q10：怎么保证 Prometheus 高可用？

- 单实例 Prometheus + 远程存储（Thanos / VictoriaMetrics）
- 双实例 Prometheus 各自抓取 + Alertmanager 去重
- K8s 里用 Prometheus Operator + HA 模式

### Q11：长期存储怎么办？

- Prometheus 本地 TSDB 默认保留 15 天
- 远端存储方案：**Thanos**（对象存储 + 查询代理）、**VictoriaMetrics**（高压缩比）、**Cortex**（多租户）

### Q12：OpenTelemetry 是什么？和 Prometheus 关系？

- OpenTelemetry = **采集层标准**（统一 SDK，统一协议 OTLP）
- Prometheus = **存储 + 查询层**
- 关系：OTel SDK 采集 → 通过 OTLP 推到 Collector → Collector 暴露 Prometheus 格式 → Prometheus 抓
- 现在趋势是"OTel 采集 + Prometheus 存储"

---

## 5 分钟讲解模板（开场用）

> "我之前在 `idbackend` 工程里接入了 Prometheus + Grafana，简单分享几个关键点。
>
> 第一，**架构选择**：用 Pull 模型，服务端主动抓 `/metrics`，对容器化和防火墙友好。
>
> 第二，**埋点位置**：通过 ASGI Middleware 拦截所有 HTTP 请求，自动采集 RED 指标——Rate、Errors、Duration。挂载顺序是在 Logging 中间件之后、Auth 中间件之前，这样慢请求日志和指标能对齐。
>
> 第三，**多 worker 坑**：uvicorn 启动 `workers=2`，prometheus_client 默认是进程内存储，会导致两个 worker 的指标互相覆盖。解决办法是设 `PROMETHEUS_MULTIPROC_DIR` 环境变量，切到 mmap 文件模式，由 `MultiProcessCollector` 自动聚合。
>
> 第四，**业务指标**：除了 HTTP 层，还在 service 层加了装饰器自动埋点，特别是 LangGraph Agent 节点做了 callback，统计 LLM token 消耗和成本——这个对生产环境特别重要。
>
> 第五，**Grafana 三层 Dashboard**：RED 看业务、USE 看资源、业务层看 LangGraph 节点耗时和 LLM 成本。
>
> 总结一下：Prometheus 的核心是**多维时间序列 + PromQL**，Grafana 是**通用可视化层**，两者解耦。生产环境只上 Metrics 是入门，三件套——Metrics、Logs、Traces——才是工程化。"

---

## 临场被问"你用过吗"的回答模板

> "我在 `idbackend` 工程里做过完整接入。从 ASGI Middleware 埋点、到多 worker 修复、再到 Grafana Dashboard 和告警规则，都跑通过。具体改动很小——核心 30 行代码，2 个 pip 依赖，4 个文件——不侵入业务代码。
>
> 最有意思的坑是多 worker 模式下的指标合并。当时两个 worker 的指标数字反复跳变，排查后发现是 prometheus_client 默认是进程内存储。修复方式是 multiproc_dir + mmap，最终 `/metrics` 端点通过 `MultiProcessCollector` 聚合所有 worker 的样本。
>
> 如果让我现在重做，我会考虑用 **OpenTelemetry** 替代手写埋点——它是采集层标准，可以同时输出到 Prometheus 和 Jaeger，减少未来的迁移成本。"
