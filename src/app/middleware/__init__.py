"""中间件 / 异常 Handler 统一管理（横切关注点）

本目录包含两类机制，目录命名沿用 middleware 但实现路径不同：

1. ASGI Middleware（洋葱模型，请求前/后执行）
   - CORS：跨域请求处理
   - Logging：请求日志
   - Permission：业务鉴权
   - Auth：身份认证

2. Exception Handler（FastAPI 异常机制，service 抛异常时被调用）
   - FileNotFoundError / FileForbiddenError / FileAuthError：业务异常
   - RequestValidationError：参数校验异常
   - Exception：兜底异常

通过以下两个函数一键装配：
- register_middlewares(app)：注册 ASGI 中间件
- register_exception_handlers(app)：注册异常 handler
"""
from fastapi import FastAPI

# ============== ASGI Middleware ==============
from src.app.middleware.cors import register_cors
from src.app.middleware.logging_middleware import LoggingMiddleware
from src.app.middleware.auth_middleware import AuthMiddleware
from src.app.middleware.permission_middleware import PermissionMiddleware

# ============== Exception Handler ==============
from src.app.middleware.exception_handlers import register_exception_handlers


def register_middlewares(app: FastAPI) -> None:
    """注册所有 ASGI 中间件

    顺序遵循"洋葱模型"——后 add 的先执行。
    请求流：
        CORS → Logging → Permission → Auth → 路由 → Auth → Permission → Logging → CORS

    设计意图：
    - CORS 最外层：跨域请求（含 OPTIONS 预检）必须先于业务处理
    - Logging 次外层：捕获所有请求耗时（含 OPTIONS）
    - Permission 内层：在业务前鉴权（依赖 Auth 注入的 context）
    - Auth 最内层：最接近路由，注入用户 context 供 Permission / 业务使用

    ⚠️ 顺序错了会导致：
    - CORS 在 Auth 内层 → 跨域请求会被 Auth 拦截
    - Logging 在 Auth 内层 → OPTIONS 预检不会被日志记录
    - Permission 在 Auth 内层 → Permission 拿不到 user context
    """
    # 1. CORS（最外层，跨域请求必须最先处理）
    register_cors(app)

    # 2. 日志中间件（次外层，记录所有请求耗时）
    app.add_middleware(LoggingMiddleware)

    # 3. 权限中间件（内层，基于 Auth 注入的 context 做业务鉴权）
    app.add_middleware(PermissionMiddleware)

    # 4. 认证中间件（最内层，注入用户 context 供 Permission 使用）
    app.add_middleware(AuthMiddleware)


__all__ = [
    # ASGI Middleware
    "LoggingMiddleware",
    "AuthMiddleware",
    "PermissionMiddleware",
    "register_middlewares",
    "register_cors",
    # Exception Handler
    "register_exception_handlers",
]