from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.infra.config import get_settings
from src.infra.database import init_db, close_db
from src.infra.redis import close_redis
from src.app.dependencies import get_storage
from src.app.middleware import register_middlewares, register_exception_handlers
from src.app.routes import register_all_routes


# ============ Lifespan（应用生命周期） ============

@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动 → 运行 → 关闭"""
    print("[idpython] 启动中...")
    try:
        await init_db()
        print("[idpython] 数据库初始化完成")
    except Exception as e:
        print(f"[idpython] 数据库初始化失败: {e}")

    try:
        storage = get_storage()
        storage.ensure_bucket()
        # avatar 目录下的对象走直链，必须设公开读策略，否则前端 GET 头像 403
        storage.set_bucket_public_read_prefix("avatar")
        print(f"[idpython] 存储后端就绪: {type(storage).__name__}")
    except Exception as e:
        print(f"[idpython] 存储初始化失败: {e}")

    yield

    print("[idpython] 关闭中...")
    await close_db()
    await close_redis()
    try:
        get_storage().close()
    except Exception:
        pass
    print("[idpython] 关闭完成")


# ============ App 构造 ============

app = FastAPI(
    title="ID-AIDemo API",
    description="厦门大学信息学院保研加分助手 API",
    version="1.0.0",
    lifespan=lifespan,
)


# ============ 横切关注点（ASGI Middleware + Exception Handler） ============

register_middlewares(app)            # CORS + Logging + Permission + Auth
register_exception_handlers(app)      # 业务异常 + 校验异常 + 兜底


# ============ 业务路由 ============

register_all_routes(app)


# ============ 启动 ============

if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        access_log=True,
        log_level="info",
    )