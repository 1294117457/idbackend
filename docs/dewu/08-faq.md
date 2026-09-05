# 08 · FAQ · 常见踩坑与排错

---

## 接入阶段

### F1：`/metrics` 端点 404

**可能原因**：
- 路由没注册：检查 `src/app/routes/__init__.py` 的 `ROUTERS` 列表
- 路径错：Prometheus 默认抓 `/metrics`，不是 `/api/metrics`
- FastAPI 路由匹配顺序：把 `metrics_router` 放 `ROUTERS` 最前面

**验证**：
```bash
curl -v http://localhost:8000/metrics
```

---

### F2：`/metrics` 端点 401 / 403

**原因**：Auth / Permission 中间件拦截了。

**修复**（二选一）：

**方案 A**：把 `/metrics` 注册成"独立路由"，不经过中间件栈（推荐，详见 `03-code-changes.md`）

**方案 B**：在中间件里加白名单
```python
EXEMPT_PATHS = {"/metrics", "/health"}

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)
        # ... 原鉴权逻辑
```

---

### F3：Prometheus Target 一直 DOWN

**排查清单**：
1. **网络**：容器内能不能访问到应用？
   ```bash
   docker exec -it idprom wget -q -O - http://idbackend:8000/metrics | head
   # 或
   docker exec -it idprom wget -q -O - http://host.docker.internal:8000/metrics | head
   ```
2. **端口**：应用真的在 8000 端口？
   ```bash
   netstat -tlnp | grep 8000
   ```
3. **路径**：Prometheus 配置的 `metrics_path` 跟应用一致？
4. **防火墙**：本机 iptables / ufw 阻断了？

**Linux Docker 特别注意**：
- `host.docker.internal` 在 Linux 上不默认可用
- 用 `172.17.0.1`（默认 bridge 网络的网关）
- 或者把 backend 加到同一个 docker network

---

### F4：指标数字不增长 / 反复跳变

**原因**：多 worker 没启用 multiproc 模式。

**修复**：
```bash
export PROMETHEUS_MULTIPROC_DIR=/tmp/prom_multiproc
mkdir -p /tmp/prom_multiproc
uvicorn main:app --workers 2
```

验证：
```bash
ls /tmp/prom_multiproc
# 应该看到 *.db 文件（每个 worker 的指标）
```

详见 [`04-multi-worker-pitfall.md`](./04-multi-worker-pitfall.md)。

---

### F5：Prometheus 启动报"data dir not writable"

**原因**：容器内 `/prometheus` 目录无权限。

**修复**：docker-compose 里 mount 出去：
```yaml
volumes:
  - prom_data:/prometheus   # 用命名 volume
# 或
  - ./prom_data:/prometheus  # 本地目录
```

---

## 运行阶段

### F6：Grafana 看不到数据

**排查清单**：
1. **数据源配置**：`http://prometheus:9090`（容器名）vs `http://localhost:9090`（本机名）
2. **时间范围**：选 "Last 5 minutes" 而不是默认的 "Last 6 hours"
3. **Query 有数据**：先在 Prometheus Graph 页面跑一遍同样的 PromQL
4. **防火墙**：Grafana 容器能不能访问 Prometheus 容器？

**快速验证**：
```bash
docker exec -it idgrafana wget -q -O - http://prometheus:9090/-/ready
# 应该返回 "Prometheus is Ready."
```

---

### F7：指标名称冲突（`Duplicated timeseries in CollectorRegistry`）

**原因**：多次 import 导致同一指标被注册两次。

**典型场景**：
- pytest 收集时多次 import 模块
- reload 模式（uvicorn --reload）下热重载

**修复**：用模块级单例（不要在函数内 `Counter("xxx", ...)`）。

---

### F8：Histogram 的 p99 算出来是 NaN

**原因**：rate 窗口内没有任何样本。

**修复**：
```promql
# 用 sum(rate(...)) 包一层 + ignoring label
histogram_quantile(
  0.99,
  sum(rate(http_request_duration_seconds_bucket[5m])) by (le)
)
```

---

### F9：指标数据"看起来对不上"业务真实情况

**常见原因**：
1. **没经过中间件**：某些路由（如 WebSocket、`/metrics` 自身）跳过了中间件
2. **请求被 4xx 拦截**：业务没真正执行，但 Prometheus 已经计入了 4xx
3. **采样率**：高 QPS 时 Prometheus 抓取间隔（5s）内的请求是聚合值，不是真实数
4. **多副本**：K8s 多 Pod 时每个 Pod 独立上报，"求和"才能得到真实 QPS

---

### F10：Cardinality 太高，Prometheus OOM

**症状**：
- Prometheus 内存持续增长
- `prometheus_tsdb_head_series` 超过预期

**排查**：
```bash
curl http://localhost:9090/api/v1/status/tsdb
# 看 numSeries
```

**修复**：
1. 找到爆 cardinality 的指标：
   ```bash
   curl http://localhost:9090/api/v1/label/__name__/values | jq '.data | length'
   ```
2. 删除或重新设计 label
3. 用 `metric_relabel_configs` 在 scrape 时丢弃高基数字段

---

## 进阶问题

### F11：怎么让 Prometheus 持久化（重启不丢数据）？

```bash
docker run -d -p 9090:9090 \
  -v $(pwd)/prom_data:/prometheus \
  prom/prometheus:latest \
  --storage.tsdb.retention.time=30d \
  --storage.tsdb.path=/prometheus
```

参数：
- `--storage.tsdb.retention.time=30d`（保留 30 天）
- `--storage.tsdb.retention.size=50GB`（按大小保留）
- 默认路径 `/prometheus`

---

### F12：怎么对接 Alertmanager？

`prometheus.yml` 加：
```yaml
alerting:
  alertmanagers:
    - static_configs:
        - targets: ['alertmanager:9093']
```

`alertmanager.yml` 配接收人（邮件 / webhook / 钉钉）。

---

### F13：怎么暴露 K8s 服务的 metrics？

```yaml
scrape_configs:
  - job_name: kubernetes-pods
    kubernetes_sd_configs:
      - role: pod
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
        action: keep
        regex: true
```

---

### F14：OpenTelemetry 怎么迁移？

如果未来想从手写埋点迁到 OTel：

1. 安装：`opentelemetry-instrumentation-fastapi`、`opentelemetry-exporter-prometheus`
2. 替换中间件
3. PromQL 不变（OTel exporter 也输出 Prometheus 格式）

不影响 Grafana Dashboard。

---

## 排错速查表

| 症状 | 第一件事 |
|---|---|
| Target DOWN | `docker exec prom wget http://target/metrics` |
| 数字不增长 | 检查 multiproc dir 是否配置 |
| Grafana 没数据 | 检查数据源 URL + 时间范围 |
| OOM | 查 cardinality，删高基数 label |
| 启动报错 Duplicated | 用模块级单例 Counter/Gauge |
| p99 = NaN | 用 `sum(rate(...)) by (le)` |
| 403 on /metrics | 路由绕开 Auth 中间件 |
| 数字反复跳变 | 多 worker 没启用 multiproc |
