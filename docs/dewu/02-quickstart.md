# 02 · Quick Start — 30 分钟跑通端到端

> 目标：用 **现有工程**（无需新增 Python 代码）接 Prometheus + Grafana，浏览器能直接看到第一张 Dashboard。
> 工程代码已经就绪（`requirements.txt` 已有 `prometheus-client`、`MetricsMiddleware` 已挂载、`/metrics` 已在 Auth/Permission 白名单），所以这一章**只讲部署**。

---

## 阶段 0：前置条件检查（1 分钟）

```bash
# 1. 后端 /metrics 端点已经能裸访问
curl -s http://localhost:8000/metrics | head -5
# 期望：看到 # HELP http_requests_total ... 之类

# 2. 服务器端持久化目录结构（idproject 部署约定）
ssh zhouch@223.109.49.63 'ls /home/project/'
# 期望看到：postgres/  redis/  minio/  prometheus/  grafana/

# 3. 远端 docker compose 文件
ssh zhouch@223.109.49.63 'ls /home/project/docker-compose.yml'
```

如果 `/metrics` 没出来 → 看 `08-faq.md` 第 F1。
如果服务器目录不存在 → 看下面的"目录初始化"。

---

## 阶段 1：服务器目录初始化（首次部署，2 分钟）

服务器上需要的目录结构：

```
/home/project/
├── docker-compose.yml         # 基础设施 + 可观测性
├── prometheus/
│   ├── prometheus.yml         # scrape 配置
│   └── data/                  # TSDB 数据（30 天保留）
├── grafana/
│   ├── provisioning/
│   │   └── datasources/
│   │       └── prometheus.yml # 数据源自动注册
│   └── data/                  # Grafana 持久化
├── postgres/data/
├── redis/data/
└── minio/data/
```

**手动初始化**（在服务器上）：

```bash
ssh zhouch@223.109.49.63
sudo mkdir -p /home/project/{prometheus/data,grafana/provisioning/datasources,grafana/data,postgres/data,redis/data,minio/data}
sudo chown -R $USER:$USER /home/project
```

---

## 阶段 2：推送配置到服务器（5 分钟）

### 2.1 推送 docker-compose.yml

```bash
# 在本地项目根
scp docs/docker-compose.yml zhouch@223.109.49.63:/home/project/docker-compose.yml
```

### 2.2 推送 Prometheus 配置

```bash
scp docs/prometheus/prometheus.yml zhouch@223.109.49.63:/home/project/prometheus/prometheus.yml
```

### 2.3 推送 Grafana 数据源配置

```bash
scp docs/grafana/provisioning/datasources/prometheus.yml \
    zhouch@223.109.49.63:/home/project/grafana/provisioning/datasources/prometheus.yml
```

### 2.4（首次）给数据目录授权

```bash
# Prometheus 容器内进程是 nobody（uid 65534）
ssh zhouch@223.109.49.63 \
  'sudo chown -R 65534:65534 /home/project/prometheus/data'

# Grafana 容器内进程是 grafana（uid 472）
ssh zhouch@223.109.49.63 \
  'sudo chown -R 472:472 /home/project/grafana/data'
```

---

## 阶段 3：起服务（5 分钟）

```bash
ssh zhouch@223.109.49.63
cd /home/project

# 起全部（postgres / redis / minio / prometheus / grafana 一起）
docker-compose up -d

# 验证：5 个容器都 healthy / running
docker-compose ps
```

期望输出：
```
NAME         STATUS          PORTS
idgrafana    Up              0.0.0.0:3000->3000/tcp
idminio      Up              0.0.0.0:9000-9001->9000-9001/tcp
idpostgres   Up (healthy)    0.0.0.0:5432->5432/tcp
idprom       Up              0.0.0.0:9090->9090/tcp
idredis      Up              0.0.0.0:6379->6379/tcp
```

---

## 阶段 4：浏览器三连看效果（2 分钟）

### 4.1 Prometheus UI

打开 http://223.109.49.63:9090

- **Status → Targets**：idbackend 应该显示 **UP**，up{job="idbackend"} = 1
- **Graph** 输入：`http_requests_total` → Execute → 看到曲线

### 4.2 Grafana UI

打开 http://223.109.49.63:3000（admin/admin）

- 左侧 ⚙️ → Data sources → 看到 **Prometheus** 已经自动配好（不用手动加）
- 左侧 + → Import → 输入 Dashboard ID `16110`（社区 FastAPI Dashboard）
- 数据源选 Prometheus → Import → 立即看到 RED 看板

### 4.3 idbackend 健康检查

```bash
curl http://223.109.49.63:8000/metrics | head -10
curl http://223.109.49.63:8000/health
```

---

## 阶段 5：造流量看图（2 分钟）

```bash
# 持续打 /health
for i in {1..200}; do
  curl -s http://223.109.49.63:8000/health > /dev/null
  sleep 0.1
done
```

回 Grafana：
- **Rate** panel 应该出现绿色曲线
- **Duration** panel 应该看到 p50 在几十 ms

---

## 阶段 6：本地复现（10 分钟）

你想在本地也看到效果？同一套配置可以本地复用。

```bash
# 1. 本地启动 idbackend
cd /home/dustp/codes/idproject/idbackend
python main.py

# 2. 本地启动基础设施 + 可观测性（用同一个 docker-compose.yml）
# 把宿主机目录换成本地路径：
sed 's|/home/project|./docker-data|g' docs/docker-compose.yml > docker-compose.local.yml
mkdir -p docker-data/{postgres/data,redis/data,minio/data,prometheus/data,grafana/data,grafana/provisioning/datasources}
cp docs/prometheus/prometheus.yml docker-data/prometheus/prometheus.yml
cp docs/grafana/provisioning/datasources/prometheus.yml \
   docker-data/grafana/provisioning/datasources/prometheus.yml

# 3. 改本地 prometheus.yml：去掉 extra_hosts（Mac/Win Docker Desktop 自带 host.docker.internal）
# Linux 还需要保留：extra_hosts: "host.docker.internal:host-gateway"

docker-compose -f docker-compose.local.yml up -d idprom idgrafana

# 4. 浏览器
# Prometheus → http://localhost:9090
# Grafana    → http://localhost:3000 (admin/admin)
```

---

## 阶段 7：常见排错

| 现象 | 原因 | 解决 |
|---|---|---|
| Prometheus Targets 显示 DOWN | 容器内无法访问宿主机 8000 | Linux 加 `extra_hosts: "host.docker.internal:host-gateway"` |
| `/metrics` 返回 401 | Auth 中间件没放行 | 检查 `auth_middleware.py` 的 `BYPASS_PATHS` 是否包含 `/metrics` |
| `/metrics` 返回空 | 应用刚启动没请求 | `curl http://localhost:8000/health` 造一个 |
| Grafana 看不到 Dashboard | 数据源 URL 用了 localhost | 改成 `http://idprom:9090`（容器名走 docker DNS） |
| Prometheus 容器重启后数据丢了 | 没挂 `/home/project/prometheus/data` | 检查 docker-compose.yml 的 volumes |
| `permission denied` on /home/project/prometheus/data | Prometheus 进程是 uid 65534 | `sudo chown -R 65534:65534 /home/project/prometheus/data` |

---

## 30 分钟总览

```
[0-1min]   前置检查（/metrics + 目录）
[1-3min]   服务器目录初始化
[3-8min]   scp 推送 3 个配置文件
[8-13min]  docker-compose up -d
[13-15min] 浏览器验证 Prometheus UI
[15-17min] 浏览器验证 Grafana UI + 导入 Dashboard
[17-19min] 造流量看图
[19-30min] 出问题排查
```

跑通后回 `README.md` 第 5 节看面试讲解提纲。
