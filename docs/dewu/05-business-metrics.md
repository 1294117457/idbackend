# 05 · 业务指标自定义（DB / Redis / LLM / Agent）

> 自动埋点只能告诉你"请求耗时多少"，**业务自定义指标**才能讲清楚架构。这是面试的加分项——展示你懂业务、可观测、性能的结合。

---

## 1. 业务指标设计原则

### 1.1 三个不要
1. **不要把 PII 当 label**（user_id、order_id、email）→ cardinality 爆炸
2. **不要为了"指标好看"做无意义的拆解** → 维护成本
3. **不要在热路径上做复杂计算**（如算 percentile）→ 业务先卡

### 1.2 一个公式
```
指标 = 业务动作 × 计数量 × 耗时分布
```

每个 service 方法至少考虑三件事：
- **Counter**：被调用了几次（成功/失败拆分）
- **Histogram**：每次耗时多少
- **Gauge**（可选）：某些"瞬时"状态（队列长度、缓存大小）

---

## 2. 你工程里值得埋点的位置

我看了你的目录结构，以下 service 有高埋点价值：

| Service | 关注指标 | 业务意义 |
|---|---|---|
| `auth_service` | 登录成功/失败次数 | 安全监控、暴力破解检测 |
| `application_service` | 加分申请提交成功率 | 业务核心流程 |
| `embedding_service` | LLM Embedding 调用耗时 | **贵**，必须监控 |
| `ai_chat_service` | LangGraph 节点级耗时 | **贵**，token 成本 |
| `calculation_service` | `simpleeval` 公式执行耗时 | 防卡死 |
| `file_service` | S3 上传/下载耗时 | IO 瓶颈 |
| `redis.py` | 缓存命中率 | 性能调优依据 |
| `database.py` | 连接池使用率 | **必修** |

---

## 3. 具体落地示例（代码片段，Review 后再写文件）

### 3.1 通用装饰器（推荐：侵入最小）

```python
# src/infra/metrics.py （新增）
"""业务指标装饰器"""
import time
from functools import wraps
from prometheus_client import Counter, Histogram

# 模块级单例
SVC_LATENCY = Histogram(
    "service_call_duration_seconds",
    "业务方法耗时",
    labelnames=("service", "method", "status"),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
SVC_COUNT = Counter(
    "service_calls_total",
    "业务方法调用次数",
    labelnames=("service", "method", "status"),
)


def track_service(service_name: str):
    """装饰器：自动给 service 方法打点

    用法：
        @track_service("auth")
        async def login(self, ...):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            method_name = func.__name__
            status = "ok"
            start = time.perf_counter()
            try:
                return await func(*args, **kwargs)
            except Exception:
                status = "error"
                raise
            finally:
                elapsed = time.perf_counter() - start
                labels = {
                    "service": service_name,
                    "method": method_name,
                    "status": status,
                }
                SVC_LATENCY.labels(**labels).observe(elapsed)
                SVC_COUNT.labels(**labels).inc()
        return wrapper
    return decorator
```

应用到 `auth_service.py`：
```python
from src.infra.metrics import track_service

class AuthService:
    @track_service("auth")
    async def login(self, ...):
        ...
```

---

### 3.2 LangGraph 节点级埋点（最有价值）

你的 `src/agent/` 目录里有 LangGraph 图，每个节点都是业务关键路径。

```python
# 在 LangGraph 节点函数里手动埋点
from src.infra.metrics import SVC_LATENCY, SVC_COUNT

async def rag_search_node(state: dict) -> dict:
    start = time.perf_counter()
    status = "ok"
    try:
        result = await do_search(state["query"])
        return {"answer": result}
    except Exception:
        status = "error"
        raise
    finally:
        labels = {"service": "agent", "method": "rag_search", "status": status}
        SVC_LATENCY.labels(**labels).observe(time.perf_counter() - start)
        SVC_COUNT.labels(**labels).inc()
```

**进阶**：用 LangGraph 的 callback 系统：
```python
from langchain.callbacks import BaseCallbackHandler

class PrometheusCallback(BaseCallbackHandler):
    def on_llm_start(self, serialized, prompts, **kwargs):
        ...
    def on_llm_end(self, response, **kwargs):
        # 上报 token 数
        LLM_TOKENS.labels(model=response.llm_output["model_name"]).inc(
            response.llm_output["token_usage"]["total_tokens"]
        )
```

---

### 3.3 数据库连接池（Gauge）

```python
# src/infra/metrics.py 增加
from prometheus_client import Gauge
from sqlalchemy import event

DB_POOL_SIZE = Gauge(
    "db_pool_connections",
    "DB 连接池状态",
    labelnames=("state",),    # checked_out / idle / total
    multiprocess_mode="livesum",
)


def setup_db_metrics(engine):
    """SQLAlchemy event hook：周期性采集连接池状态"""
    @event.listens_for(engine, "checkin")
    @event.listens_for(engine, "checkout")
    def receive(_):
        pool = engine.pool
        DB_POOL_SIZE.labels(state="total").set(pool.size())
        DB_POOL_SIZE.labels(state="checked_out").set(pool.checkedout())
        DB_POOL_SIZE.labels(state="idle").set(pool.checkedin())
```

注册（在 `database.py` 的 `init_db` 后）：
```python
setup_db_metrics(sync_engine)
```

---

### 3.4 Redis 命中率

```python
# src/infra/redis.py 包一层
class RedisMetrics:
    def __init__(self, real_redis):
        self._r = real_redis

    async def get(self, key):
        value = await self._r.get(key)
        if value is None:
            REDIS_MISS.labels(op="get").inc()
        else:
            REDIS_HIT.labels(op="get").inc()
        return value

    # ... 其他方法类似
```

`REDIS_HIT` / `REDIS_MISS`：
```python
REDIS_HIT = Counter("redis_cache_hits_total", "Redis 缓存命中", ["op"])
REDIS_MISS = Counter("redis_cache_misses_total", "Redis 缓存未命中", ["op"])
```

派生指标（Grafana 里）：
```promql
# 命中率
sum(rate(redis_cache_hits_total[5m])) /
  (sum(rate(redis_cache_hits_total[5m])) + sum(rate(redis_cache_misses_total[5m])))
```

---

### 3.5 LLM Token / 成本

这是**最值钱**的指标——LLM 贵，能算出"每个功能花多少钱"。

```python
LLM_TOKENS = Counter(
    "llm_tokens_total",
    "LLM token 消耗",
    labelnames=("model", "type"),   # type: prompt/completion
)
LLM_COST = Counter(
    "llm_cost_usd_total",
    "LLM 调用成本（美元）",
    labelnames=("model",),
)
```

价格表（举例）：
```python
PRICING = {
    "gpt-4": {"prompt": 0.03, "completion": 0.06},   # per 1k token, USD
    "gpt-3.5-turbo": {"prompt": 0.0015, "completion": 0.002},
}

def record_llm_usage(model: str, prompt_tokens: int, completion_tokens: int):
    LLM_TOKENS.labels(model=model, type="prompt").inc(prompt_tokens)
    LLM_TOKENS.labels(model=model, type="completion").inc(completion_tokens)

    pricing = PRICING.get(model, {"prompt": 0, "completion": 0})
    cost = (
        prompt_tokens / 1000 * pricing["prompt"]
        + completion_tokens / 1000 * pricing["completion"]
    )
    LLM_COST.labels(model=model).inc(cost)
```

接入方式：在 LangGraph 节点的 LLM 调用后 hook 一次。

---

## 4. 指标清单（最终版）

| 指标名 | 类型 | labels | 来源 |
|---|---|---|---|
| `http_requests_total` | Counter | method/path/status | 自动埋点 |
| `http_request_duration_seconds` | Histogram | method/path/status | 自动埋点 |
| `service_calls_total` | Counter | service/method/status | 装饰器 |
| `service_call_duration_seconds` | Histogram | service/method/status | 装饰器 |
| `db_pool_connections` | Gauge | state | SQLAlchemy event |
| `redis_cache_hits_total` | Counter | op | Redis wrapper |
| `redis_cache_misses_total` | Counter | op | Redis wrapper |
| `llm_tokens_total` | Counter | model/type | LangGraph callback |
| `llm_cost_usd_total` | Counter | model | LangGraph callback |
| `langgraph_node_duration_seconds` | Histogram | node_name | LangGraph callback |

---

## 5. Cardinality 自检

写完指标后，跑一遍：

```python
from prometheus_client import REGISTRY
print(f"total series: {sum(len(metric._metrics) for metric in REGISTRY.collect())}")
# 期望 < 10000（单个 job）
```

按 label 排序看：
```bash
curl http://localhost:8000/metrics | grep -E "^[a-z_]+{" | sort | uniq -c | sort -rn | head -20
```

如果某个指标的 series 超过 100，要警惕。
