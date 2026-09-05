# 06 · Prometheus + Grafana 部署 & Dashboard 方案

> 把工程、Prometheus、Grafana 串起来，并给出 3 套推荐 Dashboard。

---

## 1. 一键 docker-compose（推荐）

在工程根目录新建 `observability/` 目录，放以下 3 个文件。

### 1.1 `observability/docker-compose.yml`

```yaml
version: "3.9"

services:
  idbackend:
    build:
      context: ../
      dockerfile: Dockerfile
    container_name: idbackend
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql://zhouch:zhouchenhui@idpostgres:5432/iddata
      PG_VECTOR_URL: postgresql://zhouch:zhouchenhui@idpostgres:5432/iddata
      REDIS_URL: redis://:zhouchenhui@idredis:6379/1
      MINIO_ENDPOINT: http://idminio:9000
      MINIO_ACCESS_KEY: zhouch
      MINIO_SECRET_KEY: zhouchenhui
      MINIO_BUCKET: idbucket
      # 多进程指标目录（详见 04-multi-worker-pitfall.md）
      PROMETHEUS_MULTIPROC_DIR: /tmp/prom_multiproc
    volumes:
      - prom_multiproc:/tmp/prom_multiproc
    depends_on:
      - idpostgres
      - idredis
      - idminio
    networks:
      - obs

  prometheus:
    image: prom/prometheus:latest
    container_name: idprom
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
      - prom_data:/prometheus
    networks:
      - obs

  grafana:
    image: grafana/grafana:latest
    container_name: idgrafana
    ports:
      - "3000:3000"
    environment:
      GF_SECURITY_ADMIN_PASSWORD: admin
      GF_USERS_ALLOW_SIGN_UP: "false"
    volumes:
      - grafana_data:/var/lib/grafana
      - ./grafana/provisioning:/etc/grafana/provisioning
      - ./grafana/dashboards:/var/lib/grafana/dashboards
    depends_on:
      - prometheus
    networks:
      - obs

volumes:
  prom_multiproc:
  prom_data:
  grafana_data:

networks:
  obs:
    name: obs
    driver: bridge
```

### 1.2 `observability/prometheus.yml`

```yaml
global:
  scrape_interval: 5s
  evaluation_interval: 5s
  external_labels:
    cluster: local-dev
    service: idbackend

scrape_configs:
  - job_name: idbackend
    metrics_path: /metrics
    static_configs:
      - targets: ["idbackend:8000"]
        labels:
          instance: idbackend-1

  # Prometheus 自身指标（自监控）
  - job_name: prometheus
    static_configs:
      - targets: ["localhost:9090"]
```

### 1.3 一键起
```bash
cd observability
docker-compose up -d
```

访问：
- API：`http://localhost:8000/docs`
- Prometheus：`http://localhost:9090`
- Grafana：`http://localhost:3000`（admin/admin）

---

## 2. Grafana 自动配置（可选进阶）

### 2.1 数据源自动注册

新建 `observability/grafana/provisioning/datasources/datasource.yml`：
```yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: true
```

### 2.2 Dashboard 自动加载

把 Dashboard JSON 放在 `observability/grafana/dashboards/`，Grafana 启动时自动发现。

新建 `observability/grafana/provisioning/dashboards/dashboards.yml`：
```yaml
apiVersion: 1
providers:
  - name: 'default'
    orgId: 1
    folder: 'IDBackend'
    type: file
    disableDeletion: false
    updateIntervalSeconds: 10
    options:
      path: /var/lib/grafana/dashboards
```

---

## 3. Dashboard 设计：三层结构

### 3.1 Layer 1 · RED（请求视角）

**核心问题**：我的 API 现在表现怎么样？

| 面板 | PromQL | 单位 |
|---|---|---|
| Request Rate | `sum(rate(http_requests_total[1m]))` | reqps |
| Error Rate (4xx/5xx) | `sum(rate(http_requests_total{status=~"4..\|5.."}[1m])) / sum(rate(http_requests_total[1m]))` | % |
| p50 Latency | `histogram_quantile(0.5, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))` | s |
| p95 Latency | 同上，0.95 | s |
| p99 Latency | 同上，0.99 | s |
| Top 10 Slowest Endpoints | `topk(10, histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, path)))` | s |
| Status Code Distribution | `sum(rate(http_requests_total[1m])) by (status)` | reqps |

### 3.2 Layer 2 · USE（资源视角）

**核心问题**：我的机器 / 进程 / 连接池是否饱和？

| 面板 | PromQL | 来源 |
|---|---|---|
| CPU Usage | `rate(process_cpu_seconds_total[1m])` | prometheus_client 自带 |
| Memory (RSS) | `process_resident_memory_bytes` | 同上 |
| Open FDs | `process_open_fds` | 同上 |
| DB Pool Usage | `db_pool_connections{state="checked_out"} / db_pool_connections{state="total"}` | 自定义 |
| DB Pool Total | `db_pool_connections{state="total"}` | 自定义 |
| Redis Connections | `redis_connected_clients` | 需 redis_exporter |

### 3.3 Layer 3 · 业务视角

**核心问题**：业务跑得怎么样？钱花在哪里？

| 面板 | PromQL | 来源 |
|---|---|---|
| 加分申请提交成功率 | `sum(rate(service_calls_total{service="application",method="submit",status="ok"}[5m])) / sum(rate(service_calls_total{service="application",method="submit"}[5m]))` | 业务埋点 |
| LangGraph 各节点 P95 | `histogram_quantile(0.95, sum(rate(langgraph_node_duration_seconds_bucket[5m])) by (le, node_name))` | LangGraph callback |
| LLM Token 消耗速率 | `sum(rate(llm_tokens_total[5m])) by (model, type)` | LLM callback |
| LLM 成本（每小时） | `sum(increase(llm_cost_usd_total[1h]))` | LLM callback |
| Redis 命中率 | `sum(rate(redis_cache_hits_total[5m])) / (sum(rate(redis_cache_hits_total[5m])) + sum(rate(redis_cache_misses_total[5m])))` | Redis wrapper |
| 慢 SQL 计数 | `sum(rate(sql_query_duration_seconds_count{le="+Inf"}[5m]))` | SQLAlchemy event |

---

## 4. Dashboard JSON 示例（最简版）

下面是一个**最精简**的 RED Dashboard，可以直接复制到 Grafana：

```json
{
  "title": "IDBackend · RED (Basic)",
  "schemaVersion": 38,
  "panels": [
    {
      "id": 1,
      "title": "Request Rate",
      "type": "timeseries",
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
      "targets": [
        {"expr": "sum(rate(http_requests_total[1m]))", "legendFormat": "{{method}}"}
      ]
    },
    {
      "id": 2,
      "title": "P95 Latency",
      "type": "timeseries",
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
      "targets": [
        {
          "expr": "histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, path))",
          "legendFormat": "{{path}}"
        }
      ],
      "fieldConfig": {"defaults": {"unit": "s"}}
    },
    {
      "id": 3,
      "title": "Error Rate",
      "type": "timeseries",
      "gridPos": {"h": 8, "w": 24, "x": 0, "y": 8},
      "targets": [
        {
          "expr": "sum(rate(http_requests_total{status=~\"4..|5..\"}[1m])) / sum(rate(http_requests_total[1m]))",
          "legendFormat": "error %"
        }
      ],
      "fieldConfig": {"defaults": {"unit": "percentunit"}}
    }
  ]
}
```

---

## 5. 告警规则（Alerting Rules）

新建 `observability/prometheus-rules.yml`：
```yaml
groups:
  - name: idbackend-basic
    rules:
      - alert: HighErrorRate
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[5m]))
          / sum(rate(http_requests_total[5m])) > 0.05
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "5xx 错误率超过 5%"
          description: "过去 5 分钟 5xx 错误率 {{ $value | humanizePercentage }}"

      - alert: HighP99Latency
        expr: |
          histogram_quantile(0.99,
            sum(rate(http_request_duration_seconds_bucket[5m])) by (le)
          ) > 1.0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "P99 延迟 > 1s"

      - alert: DBPoolExhausted
        expr: |
          db_pool_connections{state="checked_out"}
          / db_pool_connections{state="total"} > 0.9
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "DB 连接池使用率 > 90%"
```

挂载到 `prometheus.yml`：
```yaml
rule_files:
  - "prometheus-rules.yml"

alerting:
  alertmanagers:
    - static_configs:
        - targets: ["alertmanager:9093"]
```

---

## 6. 完整启动顺序

```bash
cd observability
docker-compose up -d                          # 起 backend + prom + grafana

# 验证
curl http://localhost:8000/metrics | head -5  # 看到 Prometheus 文本
open http://localhost:9090/targets            # idbackend 应是 UP
open http://localhost:3000                    # 登录 Grafana
```

---

## 7. 升级路径

| 阶段 | 组件 |
|---|---|
| 当前 | Prometheus + Grafana（单实例） |
| 进阶 1 | + Alertmanager + 钉钉/企微 Webhook |
| 进阶 2 | + Loki（日志聚合） |
| 进阶 3 | + Tempo / Jaeger（链路追踪） |
| 进阶 4 | + Thanos / VictoriaMetrics（多集群聚合） |
| 进阶 5 | + Pyroscope（Continuous Profiling） |
