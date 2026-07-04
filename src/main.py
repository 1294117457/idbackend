"""FastAPI 应用入口"""
import sys
import os
import time
import logging

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

logger = logging.getLogger("uvicorn.access")

from src.infra.config import get_settings
from src.infra.database import init_db, close_db
from src.infra.redis import close_redis
from src.app.dependencies import get_storage
from src.app.middleware.auth_middleware import AuthMiddleware
from src.app.middleware.permission_middleware import PermissionMiddleware
from src.services.file_service import (
    FileAuthError,
    FileForbiddenError,
    FileNotFoundError,
)

from src.app.routes.auth import router as auth_router
from src.app.routes.user import router as user_router
from src.app.routes.application import router as application_router
from src.app.routes.template import router as template_router
from src.app.routes.file import router as file_router
from src.app.routes.health import router as health_router
from src.app.routes.field_config import router as field_config_router
from src.app.routes.attribute import router as attribute_router
from src.app.routes.proof import router as proof_router
from src.app.routes.demand_template import router as demand_template_router
from src.app.routes.demand_application import router as demand_application_router
from src.app.routes.role import router as role_router
from src.app.routes.permission import router as permission_router
from src.app.routes.menu import router as menu_router
from src.app.routes.system_config import router as system_config_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    print("[idpython] 启动中...")
    try:
        await init_db()
        print("[idpython] 数据库初始化完成")
    except Exception as e:
        print(f"[idpython] 数据库初始化失败: {e}")

    # 存储后端就绪（建 bucket / 建本地目录）
    try:
        storage = get_storage()
        storage.ensure_bucket()
        print(f"[idpython] 存储后端就绪: {type(storage).__name__}")
    except Exception as e:
        print(f"[idpython] 存储初始化失败: {e}")

    yield

    print("[idpython] 关闭中...")
    await close_db()
    await close_redis()
    # 释放 Storage 底层连接
    try:
        get_storage().close()
    except Exception:
        pass
    print("[idpython] 关闭完成")


app = FastAPI(
    title="ID-AIDemo API",
    description="厦门大学信息学院保研加分助手 API",
    version="1.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def log_request_time(request: Request, call_next):
    """记录每个请求的耗时，超过 500ms 打警告"""
    import sys
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    status = response.status_code
    path = request.url.path
    line = f"{elapsed_ms:7.0f}ms | {status} | {request.method} {path}\n"
    if elapsed_ms > 500 or status >= 400:
        sys.stderr.write("SLOW " + line)
    else:
        sys.stdout.write(line)
    sys.stdout.flush()
    sys.stderr.flush()
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 中间件执行顺序：后添加的先执行，所以 AuthMiddleware 在外层（先执行），PermissionMiddleware 在内层（后执行）
# AuthMiddleware 负责解析 JWT 并设置 user_id/username 到 ContextVar
# PermissionMiddleware 负责读 ContextVar 身份信息 + 查 DB 鉴权
# 如果顺序颠倒（PermissionMiddleware 在外层），则 PermissionMiddleware 先执行时 AuthMiddleware 还未设置 ContextVar
app.add_middleware(PermissionMiddleware)
app.add_middleware(AuthMiddleware)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Pydantic 参数校验失败 → 400"""
    first_err = exc.errors()[0] if exc.errors() else {}
    msg = first_err.get("msg", "请求参数错误")
    return JSONResponse(
        status_code=400,
        content={"code": 400, "msg": f"参数错误: {msg}", "data": None},
    )


# ============ 业务异常 → HTTP 统一映射 ============
# 路由无需 try/except：service 抛出业务异常，handler 自动转 JSON

async def _handle_business_error(request: Request, exc: Exception, http_code: int):
    return JSONResponse(
        status_code=http_code,
        content={"code": http_code, "msg": str(exc), "data": None},
    )


@app.exception_handler(FileNotFoundError)
async def _file_not_found_handler(request: Request, exc: FileNotFoundError):
    return await _handle_business_error(request, exc, FileNotFoundError.http_code)


@app.exception_handler(FileForbiddenError)
async def _file_forbidden_handler(request: Request, exc: FileForbiddenError):
    return await _handle_business_error(request, exc, FileForbiddenError.http_code)


@app.exception_handler(FileAuthError)
async def _file_auth_handler(request: Request, exc: FileAuthError):
    return await _handle_business_error(request, exc, FileAuthError.http_code)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """未捕获异常兜底 → 500"""
    return JSONResponse(
        status_code=500,
        content={"code": 500, "msg": "服务器内部错误", "data": None},
    )


# 注册路由
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(user_router)
app.include_router(application_router)
app.include_router(template_router)
app.include_router(file_router)
app.include_router(field_config_router)
app.include_router(attribute_router)
app.include_router(proof_router)
app.include_router(demand_template_router)
app.include_router(demand_application_router)
app.include_router(role_router)
app.include_router(permission_router)
app.include_router(menu_router)
app.include_router(system_config_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        access_log=True,
        log_level="info",
    )
