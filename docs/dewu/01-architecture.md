# 01 · Prometheus + Grafana 架构速览

> 本文是面试基础概念扫盲。讲清每个组件的定位、协作方式、为什么这套组合在 CNCF 生态里成了事实标准。

---

## 1. 三个角色，分清楚

| 组件 | 角色 | 关键能力 | 类比 |
|---|---|---|---|
| **Exporter / Instrumented App** | 数据生产者 | 暴露 `/metrics` 端点，输出 Prometheus 文本格式 | 餐厅厨房出菜窗口 |
| **Prometheus** | 数据采集 + 存储 | 主动 pull、写本地 TSDB、跑 PromQL、触发告警 | 服务员 + 仓库 |
| **Grafana** | 数据可视化 | 接任意时序库、画图、写 Dashboard | 餐厅大屏 |

**常见误区**：以为 Grafana 在"采集"数据。它**只查询不采集**，所有数据都从 Prometheus 拉。

---

## 2. Prometheus 工作流（5 步）

```
   ┌──────────┐
   │ App A    │── /metrics ─┐
   │ App B    │── /metrics  │
   │ Exporter │── /metrics ─┼───► Prometheus ────► TSDB
   └──────────┘             │   - scrape          │
                            │   - eval rules      │
                            │   - alert           │
                            └─────────────────────┘
                                       │
                                       ▼
                              ┌─────────────────┐
                              │ Grafana (查询)  │
                              │ Alertmanager    │
                              └─────────────────┘
```

1. **Scrape**：每隔 N 秒从配置的 target 拉 `/metrics`（HTTP GET）
2. **Parse**：解析 Prometheus 文本格式 → 内存中维护时间序列
3. **Persist**：把样本 append 到本地 TSDB（chunk 文件 + WAL）
4. **Query**：HTTP 暴露 `/api/v1/query` 给 PromQL 调用方（Grafana、Alertmanager）
5. **Alert**：按 alerting rules 周期评估，触发后推给 Alertmanager

---

## 3. Pull vs Push（面试高频）

| 维度 | Pull（Prometheus） | Push（StatsD / Telegraf） |
|---|---|---|
| **方向** | 服务端主动拉 | 客户端主动推 |
| **失败检测** | scrape 失败 = 服务挂了 | 需要额外心跳 |
| **服务发现** | 强依赖（K8s SD、文件 SD） | 不需要 |
| **短任务** | 不友好（任务跑完就抓不到） | 友好（Pushgateway 中转） |
| **网络/防火墙** | 出方向即可 | 需要入站规则 |
| **生态** | CNCF 主流 | 旧时代主流 |

**面试标准答案**：
> "Prometheus 选 Pull 是因为它是面向**长期运行服务**的——失败检测和服务发现能复用同一套机制。如果遇到批处理任务（CI、Spark 任务），Prometheus 提供了 Pushgateway 作为'中转'，但官方建议尽量用 Pull + sidecar。"

---

## 4. Metric 类型四件套

### 4.1 Counter（只增不减）
```promql
http_requests_total{method="GET", path="/api/users"} 1234
```
- 重启后归零（Prometheus 处理 `rate()` 时会自动补偿）
- 典型用途：请求总数、错误总数、字节数

### 4.2 Gauge（瞬时值）
```promql
redis_connections_active 8
process_memory_bytes 134217728
```
- 可增可减
- 典型用途：CPU、内存、连接池、队列深度、在线人数

### 4.3 Histogram（分布）
```promql
http_request_duration_seconds_bucket{le="0.1"} 1000
http_request_duration_seconds_bucket{le="0.5"} 1900
http_request_duration_seconds_count 2000
http_request_duration_seconds_sum 234.5
```
- 暴露 `<name>_bucket{le=...}` + `<name>_count` + `<name>_sum`
- 典型用途：请求耗时、响应大小
- 关键 PromQL：`histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))`

### 4.4 Summary（客户端分位数）
- 类似 Histogram，但 quantile 在客户端算
- **不能跨实例聚合**——这是为啥大多数场景用 Histogram
- 极少用

---

## 5. Label 与 Cardinality（最常踩的坑）

```promql
# ❌ 错误：每个用户一个时间序列
http_requests_total{user_id="user_12345"} 1
http_requests_total{user_id="user_12346"} 1
# ... 100 万用户 → 100 万条 series

# ✅ 正确：粗粒度维度
http_requests_total{endpoint="/api/users", method="GET", status="200"} 1234
```

**经验法则**：
- **任意 label 的取值数 ≤ 100**
- **总 series 数 ≤ 10000**（单 job）
- 超过这个量级要警惕
- 高基数字段（user_id、order_id、email）**永远不要**当 label
- 想看"按用户聚合"应该用日志（ELK/Loki），不是 Metrics

---

## 6. PromQL 五大函数（够面试用）

| 函数 | 作用 | 例子 |
|---|---|---|
| `rate()` | 算每秒速率（counter） | `rate(http_requests_total[5m])` |
| `increase()` | 时间窗口内的增量 | `increase(http_requests_total[1h])` |
| `histogram_quantile()` | 算分位数 | `histogram_quantile(0.99, ...)` |
| `sum by / avg by` | 聚合 | `sum(rate(...[5m])) by (status)` |
| `topk / bottomk` | TopN | `topk(5, rate(...[5m]))` |

**核心心法**：
> rate() 用于 counter（必须先 rate 再 sum，不然是累加值），histogram_quantile() 必须配 sum(rate(...)) by (le)。

---

## 7. Grafana 是什么、不是什么

**是**：
- 可视化面板（Dashboard 模板支持 import/export）
- 多数据源（Prometheus / Loki / MySQL / ES / InfluxDB）
- 告警（从 v4 起内置 alerting）

**不是**：
- 存储（不存数据）
- 采集（不主动抓）

**Dashboard JSON 结构**：
```json
{
  "panels": [
    {
      "title": "P99 Latency",
      "type": "timeseries",
      "targets": [{"expr": "histogram_quantile(0.99, ...)", "datasource": "Prometheus"}]
    }
  ]
}
```

---

## 8. 完整的可观测性三角

```
                Metrics (Prometheus)
                      ▲
                      │
   Logs (Loki/ELK) ───┼─── Traces (Jaeger/Tempo)
                      │
                      ▼
                Profiles (Pyroscope/Parca)
```

**面试加分项**：
> "Metrics 告诉你'系统挂了'，Logs 告诉你'为什么挂了'，Traces 告诉你'哪一段挂了'。生产环境只上 Metrics 是入门，上全三件套才是工程化。"

---

## 9. CNCF 生态一览

| 类别 | 项目 |
|---|---|
| Metrics | **Prometheus**, Thanos, Cortex, VictoriaMetrics |
| Logs | **Loki**, ELK, Fluentbit |
| Traces | **Jaeger**, Tempo, Zipkin |
| Visualization | **Grafana** |
| Alert | **Alertmanager**, Grafana Alerting |
| Profiling | Pyroscope, Parca |
| Collectors | **OpenTelemetry Collector**, Vector |
| Service Mesh | Istio (自带 Prometheus 指标) |

---

## 10. 一句话总结

> **Prometheus = 拉模型 + TSDB + PromQL；Grafana = 通用可视化层。两者靠 PromQL 解耦，生态用 OpenTelemetry 统一埋点。**
