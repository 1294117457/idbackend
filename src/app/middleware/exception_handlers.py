"""异常 Handler 集中管理

注意：本模块实现的是 FastAPI 异常 handler（@app.exception_handler /
app.add_exception_handler），不是 ASGI Middleware。但放在 middleware 目录下
作为"横切关注点"统一管理。

为什么不用 ASGI Middleware 捕获异常？
- FastAPI 路由层抛出的异常已经被 @app.exception_handler 消费
- BaseHTTPMiddleware 捕获不到路由层的异常
- FastAPI 官方推荐用 app.add_exception_handler() 处理业务异常

为什么要放在 middleware 目录而不是独立目录？
- 异常处理是典型的横切关注点（影响每个业务路由）
- 和 ASGI Middleware 同属"非业务路由的关注点"，视觉集中
- 文件顶部加注释说清楚机制差异即可
"""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.services.file_service import FileNotFoundError


# ============== 通用工具 ==============

async def _to_business_response(exc: Exception, http_code: int) -> JSONResponse:
    """业务异常 → 统一 JSON 响应（code / msg / data 三段式）"""
    return JSONResponse(
        status_code=http_code,
        content={"code": http_code, "msg": str(exc), "data": None},
    )


# ============== 业务异常 handlers ==============

async def file_not_found_handler(request: Request, exc: FileNotFoundError):
    return await _to_business_response(exc, FileNotFoundError.http_code)


# ⚠️ 暂时停用：file_service.py 还没定义以下异常，等业务层加上再启用
# async def file_forbidden_handler(request: Request, exc: FileForbiddenError):
#     return await _to_business_response(exc, FileForbiddenError.http_code)
#
# async def file_auth_handler(request: Request, exc: FileAuthError):
#     return await _to_business_response(exc, FileAuthError.http_code)


# ============== 校验异常 handler ==============

async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Pydantic 参数校验失败 → 400"""
    first_err = exc.errors()[0] if exc.errors() else {}
    msg = first_err.get("msg", "请求参数错误")
    return JSONResponse(
        status_code=400,
        content={"code": 400, "msg": f"参数错误: {msg}", "data": None},
    )


# ============== 兜底 handler ==============

async def global_exception_handler(request: Request, exc: Exception):
    """未捕获异常兜底 → 500（生产环境应记录 traceback 到日志）"""
    return JSONResponse(
        status_code=500,
        content={"code": 500, "msg": "服务器内部错误", "data": None},
    )


# ============== 注册入口 ==============

def register_exception_handlers(app: FastAPI) -> None:
    """把所有异常 handler 一次性注册到 app

    路由无需 try/except：service 抛出业务异常，handler 自动转 JSON。
    """
    app.add_exception_handler(FileNotFoundError, file_not_found_handler)
    # ⚠️ 等业务层补全 FileForbiddenError / FileAuthError 后再启用下面两行
    # app.add_exception_handler(FileForbiddenError, file_forbidden_handler)
    # app.add_exception_handler(FileAuthError, file_auth_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, global_exception_handler)


__all__ = ["register_exception_handlers"]