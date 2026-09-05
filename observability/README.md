# Observability · Prometheus + Grafana

`idbackend` 的可观测性套件。详见 [`../docs/dewu/`](../docs/dewu/)。

## 启动

```bash
cd observability
docker-compose up -d
```

| 服务 | 端口 | 访问 |
|---|---|---|
| Prometheus | 9090 | http://localhost:9090 |
| Grafana | 3000 | http://localhost:3000 (admin/admin) |

## 验证 Prometheus 是否抓到数据

1. **Target UP 状态**：`http://localhost:9090/targets` —— `idbackend` 应为 UP
2. **指标查询**：`http://localhost:9090/graph`，输入 `http_requests_total`，点 Execute
3. **如果 Target DOWN**：见 `docs/dewu/08-faq.md` 的 F3

## 配置 Grafana 数据源

1. 登录 Grafana → ⚙️ Data sources → Add data source → Prometheus
2. URL 填 `http://prometheus:9090`（**容器名**，不是 localhost）
3. 点 Save & test，看绿色 "Data source is working"

## 导入 Dashboard

推荐：
- **官方 FastAPI Dashboard**：[Grafana Dashboards](https://grafana.com/grafana/dashboards/16110) ID `16110`
- 自建 RED 看板：JSON 见 `../docs/dewu/06-grafana-dashboards.md`

## 多 worker 注意事项

如果 `idbackend` 跑 `WORKERS > 1`（Dockerfile 默认 2），必须设置：

```bash
export PROMETHEUS_MULTIPROC_DIR=/tmp/prom_multiproc
```

否则两个 worker 的指标会互相覆盖、数据反复跳变。详见 `../docs/dewu/04-multi-worker-pitfall.md`。

## 故障排查速查

| 现象 | 排查 |
|---|---|
| Target DOWN | `docker exec idprom wget -q -O - http://host.docker.internal:8000/metrics` |
| Grafana 没数据 | 检查数据源 URL（容器名 vs localhost）+ 时间范围 |
| 数字反复跳变 | 多 worker 没启用 multiproc_dir |
| p99 = NaN | `histogram_quantile()` 必须配 `sum(rate(...)) by (le)` |
