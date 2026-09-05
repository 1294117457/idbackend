"""Prometheus 抓取端点

单独的 router（不带 /api 前缀），由 AuthMiddleware / PermissionMiddleware
通过白名单放行。MetricsMiddleware 内部对 /metrics 自身 SKIP，避免自抓自。
"""
from fastapi import APIRouter

from src.app.middleware.metrics_middleware import metrics_endpoint

router = APIRouter(tags=["可观测性"])

router.add_api_route(
    "/metrics",
    metrics_endpoint,
    methods=["GET"],
    include_in_schema=False,   # 不进 Swagger
)


__all__ = ["router"]
