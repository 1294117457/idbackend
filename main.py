from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from src.app.dependencies import get_storage, set_storage, clear_storage
from src.app.middleware import register_exception_handlers, register_middlewares
from src.app.routes import register_all_routes
from src.infra.config import get_settings
from src.infra.database import close_db, sync_engine
from src.infra.redis import close_redis
from src.models.base import Base


# ============ Schema 同步（幂等） ============

def _sync_schema_blocking() -> None:
    import src.models  # noqa: F401  isort:skip
    Base.metadata.create_all(sync_engine)
    table_count = len(Base.metadata.tables)
    print(f"[idpython] schema synced via Base.metadata.create_all ({table_count} tables)")


# ============ Lifespan（应用生命周期） ============

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[idpython] 启动中...")

    try:
        from src.infra.storage import create_storage
        storage = create_storage()
        set_storage(storage)
        storage.ensure_bucket()
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
    clear_storage()
    print("[idpython] 关闭完成")


# ============ App 构造（保持 module-level，方便 `uvicorn main:app` 启动） ============

app = FastAPI(
    title="ID-AIDemo API",
    description="厦门大学信息学院保研加分助手 API",
    version="1.0.0",
    lifespan=lifespan,
)


# ============ 横切关注点（ASGI Middleware + Exception Handler） ============

register_middlewares(app)             # CORS + Logging + Permission + Auth
register_exception_handlers(app)      # 业务异常 + 校验异常 + 兜底


# ============ 业务路由 ============

register_all_routes(app)


# ============ 启动入口 ============

def main() -> None:

    settings = get_settings()

    # 1. Schema 同步（幂等，可重复跑）
    _sync_schema_blocking()

    # 2. 起 web server（workers>1 时关闭 reload 避免冲突）
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
        workers=2,
        log_level="info",
    )


if __name__ == "__main__":
    main()
