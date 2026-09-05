"""Prometheus 指标中间件（RED: Rate / Errors / Duration）

设计要点：
1. 沿用 LoggingMiddleware 的 BaseHTTPMiddleware 风格
2. 路径标签用 FastAPI 的 route template（避免 cardinality 爆炸）
3. /metrics 端点单独路由，不通过中间件（避免自抓自）
4. 多 worker 模式：详见 docs/dewu/04-multi-worker-pitfall.md
   必须设置 PROMETHEUS_MULTIPROC_DIR 环境变量
"""
import os
import sys
import time
from typing import Awaitable, Callable

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    CollectorRegistry,
    generate_latest,
    multiprocess,
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
    # 多 worker 模式：所有 worker 累加，而不是各自取最大值
    multiprocess_mode="livesum",
)


# ============== 中间件 ==============

class MetricsMiddleware(BaseHTTPMiddleware):
    """请求级 RED 指标采集"""

    # 不采集 /metrics 自身（避免自抓自）
    SKIP_PATHS = {"/metrics"}

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path
        if path in self.SKIP_PATHS:
            return await call_next(request)

        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start

        # 关键：用 route template 替代 raw path
        # 例如 /api/users/123 → /api/users/{user_id}
        route = request.scope.get("route")
        path_template = getattr(route, "path", path)
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

    由 src/app/routes/metrics.py 单独注册到 FastAPI app，
    通过 AuthMiddleware / PermissionMiddleware 的白名单放行。

    ⚠️ 多 worker 模式（uvicorn --workers N > 1）：
    各 worker 进程内存独立，必须用 MultiProcessCollector + mmap 目录聚合，
    否则每个 scrape 只能看到当前进程的指标 → 数据跳变/丢失。
    判断标准：环境变量 PROMETHEUS_MULTIPROC_DIR 是否存在且非空。
    """
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        data = generate_latest(registry)
    else:
        data = generate_latest()

    return Response(data, media_type=CONTENT_TYPE_LATEST)


__all__ = ["MetricsMiddleware", "metrics_endpoint", "REQ_LATENCY", "REQ_COUNT"]
