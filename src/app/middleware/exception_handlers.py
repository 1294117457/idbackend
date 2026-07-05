"""异常 Handler 集中管理

注意：本模块实现的是 FastAPI 异常 handler（@app.exception_handler /
app.add_exception_handler），不是 ASGI Middleware。但放在 middleware 目录下
作为"横切关注点"统一管理。

设计（v2）：
- 业务异常统一继承 BusinessError（见 src.app.schemas.errors）
- handler 只注册基类一个：add_exception_handler(BusinessError, ...)
- 新增业务异常子类时，**不需要修改本文件**——MRO 自动匹配
- 兜底：未捕获异常 → 500；Pydantic 校验失败 → 400 + VALIDATION_ERROR

为什么不用 ASGI Middleware 捕获异常？
- FastAPI 路由层抛出的异常已经被 @app.exception_handler 消费
- BaseHTTPMiddleware 捕获不到路由层的异常
- FastAPI 官方推荐用 app.add_exception_handler() 处理业务异常
"""
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.app.schemas.errors import BusinessError


# ============== 通用工具 ==============

def _to_business_response(
    exc: BusinessError,
    *,
    extra_data: Optional[Dict[str, Any]] = None,
) -> JSONResponse:
    """业务异常 → 统一 JSON 响应（code/errorCode/msg/data 四段式）

    extra_data 用于携带额外结构化信息（如"activeApplicationCount"等业务字段）。
    """
    payload = {
        "code": exc.http_code,
        "errorCode": exc.error_code,
        "msg": exc.message,
        "data": extra_data,
    }
    return JSONResponse(status_code=exc.http_code, content=payload)


# ============== 业务异常 handler（基类一次接住） ==============

async def business_error_handler(request: Request, exc: BusinessError):
    """一个 handler 接住所有 BusinessError 子类（NotFoundError / BadRequestError / ...）。

    路由无需 try/except：service 抛出任意业务异常，自动转 JSON。
    """
    return _to_business_response(exc)


# ============== 校验异常 handler ==============

async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Pydantic 参数校验失败 → 400"""
    first_err = exc.errors()[0] if exc.errors() else {}
    msg = first_err.get("msg", "请求参数错误")
    return JSONResponse(
        status_code=400,
        content={
            "code": 400,
            "errorCode": "VALIDATION_ERROR",
            "msg": f"参数错误: {msg}",
            "data": None,
        },
    )


# ============== 兜底 handler ==============

async def global_exception_handler(request: Request, exc: Exception):
    """未捕获异常兜底 → 500（生产环境应记录 traceback 到日志）"""
    return JSONResponse(
        status_code=500,
        content={
            "code": 500,
            "errorCode": "INTERNAL_ERROR",
            "msg": "服务器内部错误",
            "data": None,
        },
    )


# ============== 注册入口 ==============

def register_exception_handlers(app: FastAPI) -> None:
    """一次性注册全部异常 handler。

    业务异常用基类一次注册，新加异常子类无需改本文件。
    """
    app.add_exception_handler(BusinessError, business_error_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, global_exception_handler)


__all__ = [
    "register_exception_handlers",
    "business_error_handler",
    "validation_exception_handler",
    "global_exception_handler",
]