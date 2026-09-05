# 03 · 工程改造清单（Review 用，暂不落地）

> 本文档给出**最小、可逆、易回滚**的改造方案。所有改动都集中在以下文件：
> 1. `requirements.txt`（+2 行）
> 2. `src/app/middleware/metrics_middleware.py`（**新增**）
> 3. `src/app/middleware/__init__.py`（+1 行挂载）
> 4. `src/app/routes/__init__.py` 或新增 `src/app/routes/metrics.py`（+1 个路由）
> 5. `main.py`（可选，启用多进程时改）
>
> **不修改任何业务代码**（service / repository / model / agent 都不动）。

---

## 文件 1：`requirements.txt`（追加）

```diff
 # HTML 净化（防 XSS）—— 用于 Template.description 富文本字段
 nh3>=0.2.17
+
+# Observability（Prometheus + Grafana）
+prometheus-client>=0.20.0
+prometheus-fastapi-instrumentator>=7.0.0
```

---

## 文件 2：**新增** `src/app/middleware/metrics_middleware.py`

风格完全沿用你工程里 `LoggingMiddleware` 的写法（`BaseHTTPMiddleware` + `sys.stdout` 输出），保持代码风格统一。

```python
"""Prometheus 指标中间件（RED: Rate / Errors / Duration）

设计要点：
1. 沿用 LoggingMiddleware 的 BaseHTTPMiddleware 风格
2. 路径标签用 FastAPI 的 route template（避免 cardinality 爆炸）
3. metrics 端点 / 单独路由，不通过 middleware（避免自抓自）
4. 多 worker 模式详见 04-multi-worker-pitfall.md
"""
import sys
import time
from typing import Awaitable, Callable

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


# ============== 指标定义（模块级单例） ==============

# 走 RED 方法：Rate / Errors / Duration
REQ_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP 请求耗时（秒）",
    labelnames=("method", "path", "status"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
REQ_COUNT = Counter(
    "http_requests_total",
    "HTTP 请求总数",
    labelnames=("method", "path", "status"),
)
REQ_INPROGRESS = Counter  # Gauge 也行，单进程足够


# ============== 中间件 ==============

class MetricsMiddleware(BaseHTTPMiddleware):
    """请求级 RED 指标采集"""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start

        # 关键：用 route template 替代 raw path
        # 例如 /api/users/123 → /api/users/{user_id}
        route = request.scope.get("route")
        path_template = getattr(route, "path", request.url.path)
        labels = {
            "method": request.method,
            "path": path_template,
            "status": str(response.status_code),
        }

        REQ_LATENCY.labels(**labels).observe(elapsed)
        REQ_COUNT.labels(**labels).inc()

        # 慢请求同时打到 stderr（与 LoggingMiddleware 行为一致）
        if elapsed > 0.5 or response.status_code >= 400:
            sys.stderr.write(
                f"METRIC | {elapsed*1000:7.0f}ms | "
                f"{labels['status']} | {labels['method']} {labels['path']}\n"
            )
            sys.stderr.flush()

        return response


# ============== /metrics 端点 ==============

async def metrics_endpoint(_: Request) -> Response:
    """Prometheus scrape 端点

    注意：/metrics 自身不能经过 MetricsMiddleware（避免自抓自）
    —— 把它注册成独立的、不带 middleware 的路由即可。
    """
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


__all__ = ["MetricsMiddleware", "metrics_endpoint"]
```

---

## 文件 3：`src/app/middleware/__init__.py`（挂载）

在 `register_middlewares` 里、Logging 之后加一行：

```diff
 from src.app.middleware.cors import register_cors
 from src.app.middleware.logging_middleware import LoggingMiddleware
+from src.app.middleware.metrics_middleware import MetricsMiddleware
 from src.app.middleware.auth_middleware import AuthMiddleware
 from src.app.middleware.permission_middleware import PermissionMiddleware

 def register_middlewares(app: FastAPI) -> None:
     register_cors(app)
     app.add_middleware(LoggingMiddleware)
+    app.add_middleware(MetricsMiddleware)         # NEW：紧跟 Logging
     app.add_middleware(PermissionMiddleware)
     app.add_middleware(AuthMiddleware)
```

并在文件顶部 `__all__` 里加 `"MetricsMiddleware"`。

---

## 文件 4：**新增** `src/app/routes/metrics.py`（独立路由）

单独写一个路由文件，避开 Auth / Permission 中间件——`/metrics` 必须能裸访问。

```python
"""Prometheus 抓取端点"""
from fastapi import APIRouter

from src.app.middleware.metrics_middleware import metrics_endpoint

router = APIRouter(tags=["可观测性"])

# 注意：这里不走任何 middleware（Auth / Permission 都没经过）
router.add_api_route(
    "/metrics",
    metrics_endpoint,
    methods=["GET"],
    include_in_schema=False,   # 不进 Swagger
)
```

然后在 `src/app/routes/__init__.py` 的 `ROUTERS` 列表**最前面**注册（让它比 Auth 中间件先匹配——但因为它直接挂到 app 上不走中间件栈，所以位置无所谓）：

```diff
 from src.app.routes.ai_chat import router as ai_chat_router
 from src.app.routes.export import router as export_router
+from src.app.routes.metrics import router as metrics_router

 ROUTERS = [
+    metrics_router,           # NEW：/metrics 端点
     health_router,
     auth_router,
     ...
 ]
```

---

## 文件 5：`main.py`（**多 worker 时必改**，单进程可不动）

详见 `04-multi-worker-pitfall.md`。要点：
- 单进程（`workers=1`）：**不改**——默认行为即可
- 多进程（`workers>1`，如 Dockerfile 默认 `2`）：启动时清空 `prometheus_multiproc_dir`

```diff
 def main() -> None:
     settings = get_settings()
     _sync_schema_blocking()

+    # 多 worker 模式：Prometheus 指标合并需要 multiproc dir
+    import os, shutil
+    multiproc_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
+    if settings.WORKERS > 1 and multiproc_dir:
+        if os.path.exists(multiproc_dir):
+            shutil.rmtree(multiproc_dir)
+        os.makedirs(multiproc_dir, exist_ok=True)
+
     uvicorn.run(
         "main:app",
         host=settings.HOST,
         port=settings.PORT,
         reload=False,
-        workers=1,
+        workers=settings.WORKERS,    # 假设 .env 里配 WORKERS=2
         log_level="info",
     )
```

---

## 文件 6（可选）：`src/infra/config.py`（暴露 WORKERS 配置）

如果不想改 `main.py` 的 workers 写法，保持 `workers=1` 不动也行——面试时演示用单进程即可。

---

## 改完后的"挂载顺序"

```
   request
     │
     ▼
 ┌─────────┐
 │  CORS   │   跨域最先处理
 └─────────┘
     ▼
 ┌─────────┐
 │ Logging │   记录所有耗时
 └─────────┘
     ▼
 ┌─────────┐
 │ Metrics │   ← NEW：采集 RED 指标
 └─────────┘
     ▼
 ┌─────────┐
 │Permission│
 └─────────┘
     ▼
 ┌─────────┐
 │  Auth   │   注入 user context
 └─────────┘
     ▼
   route
   ├─ /metrics  → 直接返回 Prometheus 文本（不走中间件栈）
   ├─ /health
   └─ /api/*
```

---

## 验证步骤

启动后：

```bash
# 1. 检查 /metrics 端点
curl http://localhost:8000/metrics | head -30
# 期望看到：
# # HELP http_request_duration_seconds ...
# # TYPE http_request_duration_seconds histogram
# http_request_duration_seconds_bucket{...,le="0.005"} 0.0
# ...

# 2. 造一次流量
curl http://localhost:8000/health

# 3. 再查 /metrics
curl http://localhost:8000/metrics | grep http_requests_total
# 期望看到 http_requests_total{method="GET",path="/health",status="200"} 1.0
```

如果一切正常，Prometheus 那边就能抓到数据了。

---

## 回滚

所有改动都是**新增或挂载式**的，不需要回滚时：
1. `requirements.txt` 删 2 行
2. 删除 `src/app/middleware/metrics_middleware.py`
3. 删除 `src/app/routes/metrics.py`
4. `src/app/middleware/__init__.py` 删 1 行 `add_middleware`
5. `src/app/routes/__init__.py` 删 2 行（import + ROUTERS）
6. `main.py` 还原

零侵入。
