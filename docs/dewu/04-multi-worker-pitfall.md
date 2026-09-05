# 04 · 多 Worker 模式下的 Prometheus 指标合并（高频考点）

> 你工程里的 `Dockerfile` 启动命令是：
> ```dockerfile
> CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
> ```
> `workers=2` 在 Prometheus 接入里**会出问题**——这是面试高频考点，本文档单独讲清楚。

---

## 1. 问题是什么

`prometheus_client` 默认是**进程内**的：

```
┌─────────┐         ┌─────────┐
│ Worker 0│         │ Worker 1│
│ metric A│         │ metric A│  ← 各自一份独立的 in-memory 计数
│ metric B│         │ metric B│
└────┬────┘         └────┬────┘
     │   /metrics        │
     └──────┬─────────────┘
            ▼
       Prometheus 抓一次
       → 只能抓到其中一个 worker 的数据
       → 数值会**反复跳变**（抓 worker 0、抓 worker 1、抓 worker 0...）
```

**症状**：
- `http_requests_total` 一直是 worker 0 的本地值
- 即使增加流量，数字不增长（或增长到 worker 0 那一份）
- QPS 看起来像心跳曲线，不平滑

---

## 2. 解决：`prometheus_multiproc_dir`

每个 worker 把指标写到磁盘文件，Prometheus 抓的时候**自动 merge**：

```
┌─────────┐                 ┌─────────┐
│ Worker 0│── write ──► mmap file         │
└─────────┘                 │ gauge_*.db │
                            │ counter_* │
┌─────────┐                 │ histogram │
│ Worker 1│── write ──► mmap file         │
└─────────┘                 └─────┬─────┘
                                  │
                                  ▼
                          /metrics 端点
                          （自动 aggregate 所有 worker）
```

### 启用步骤

#### Step 1：环境变量（**必须在 import prometheus_client 之前设置**）

```python
# main.py 顶部，最先执行
import os
os.environ.setdefault("PROMETHEUS_MULTIPROC_DIR", "/tmp/prom_multiproc")

import uvicorn
from fastapi import FastAPI
# ...
```

或者在启动命令前：
```bash
export PROMETHEUS_MULTIPROC_DIR=/tmp/prom_multiproc
uvicorn main:app --workers 2
```

Docker：
```dockerfile
ENV PROMETHEUS_MULTIPROC_DIR=/tmp/prom_multiproc
```

#### Step 2：启动时清理目录

```python
# main.py 里 _sync_schema_blocking() 之后
import shutil
multiproc = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
if multiproc:
    if os.path.exists(multiproc):
        shutil.rmtree(multiproc)
    os.makedirs(multiproc, exist_ok=True)
```

> ⚠️ 一定要清！否则上次进程崩溃留下的 stale 文件会被聚合进来，导致数字虚高。

#### Step 3：worker 子进程 fork 时也要清吗？

**不要清**。`multiproc_dir` 在 worker fork 之后必须保留。**只有 master 进程启动时清一次**。

---

## 3. 关键细节

### 3.1 Gauge / Counter / Histogram 的多进程行为差异

| 类型 | 多进程模式 | 备注 |
|---|---|---|
| **Counter** | 所有 worker 求和 ✅ | 默认即正确 |
| **Gauge** | 需要指定聚合方式 ⚠️ | 详见下 |
| **Histogram** | 所有 worker 求和 ✅ | 默认即正确 |
| **Summary** | **不支持**多进程 ❌ | 别用 Summary |

### 3.2 Gauge 的特殊处理

```python
from prometheus_client import Gauge, multiprocess

# 多进程 Gauge：必须传 multiprocess_mode
WORKERS_ACTIVE = Gauge(
    "workers_active_count",
    "在线 worker 数",
    multiprocess_mode="livesum",     # 或 "liveall"、"min"、"max"、"mostrecent"
)
```

可选值：
- `livesum`（默认）：所有还活着的 worker 求和
- `liveall`：列每个 worker 的值
- `min/max/mostrecent`：取对应聚合

> **面试考点**：你工程里如果想监控"DB 连接池使用率"（Gauge），必须显式指定 `multiprocess_mode`。

### 3.3 Histogram 桶的选择

默认桶：`[.005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5, 10]`

对绝大多数 web 服务**够用**，但：
- 如果你的服务 p99 > 10s：把 `10` 改成 `30` 或加 `60`
- 如果 API 极快（< 5ms）：把 `.005` 改成 `.001`

**不要**为了"精确"加几百个桶——会爆 cardinality。

### 3.4 uvicorn `--workers > 1` 时的 fork 顺序

```
master process
  ├── fork() ──► worker 0（继承 master 的 metric registry）
  └── fork() ──► worker 1（继承 master 的 metric registry）
```

每个 worker 写自己的 mmap 文件，互不干扰。Prometheus 抓 `/metrics` 时由 `generate_latest()` 统一聚合。

---

## 4. 验证多进程模式生效

启动后：

```bash
# 1. 查 multiproc 目录
ls /tmp/prom_multiproc
# 期望看到类似：
# counter_12345.db
# gauge_67890.db
# histogram_23456.db
# （每个文件 = 一个 worker 的 metric 类别）

# 2. 多次抓 /metrics，看请求数是否累加
for i in {1..5}; do
  curl -s http://localhost:8000/metrics | grep http_requests_total | head -1
done
# 期望每次数字都比上次大（说明两个 worker 的数据在聚合）
```

如果数字反复跳变回小值，说明 multiproc 没生效。

---

## 5. 面试标准答案

> **Q: 你的服务有 4 个 worker，Prometheus 抓到的指标为什么是正确的？**
>
> A: 启动时设置 `PROMETHEUS_MULTIPROC_DIR` 环境变量，prometheus_client 会从内存模式切换到 mmap 文件模式。每个 worker 把自己的指标写入独立文件，`/metrics` 端点通过 `MultiProcessCollector` 聚合所有 worker 的样本。Counter 和 Histogram 自动求和；Gauge 需要指定 `multiprocess_mode`（`livesum` / `mostrecent` 等）。**注意 Summary 不支持多进程，所以生产中用 Histogram 替代**。

---

## 6. 简化决策树

```
你的部署形态？
├── 单进程（workers=1）──→ 什么都不用做 ✅
├── gunicorn + uvicorn workers ──→ multiproc_dir 必开 ⚠️
└── Kubernetes Pod（每个 Pod 一个进程）──→ 什么都不用做 ✅
    └── 但要配 Prometheus ServiceMonitor 做服务发现
```

你工程当前是 `uvicorn --workers 2`，属于第二种，**必须开 multiproc**。
