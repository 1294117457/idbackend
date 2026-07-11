"""idbackend 应用入口。

启动方式（推荐）：
    python -m src.main        ← 启动时自动同步 schema（Base.metadata.create_all）
    uvicorn main:app           ← 直接启动 web server（**不会同步 schema**）

Schema 同步策略：
    本项目**不使用 alembic**。所有 model 通过 SQLAlchemy 的 `Base.metadata.create_all()`
    在进程启动时同步到 DB。

    - 表不存在 → CREATE TABLE
    - 表已存在 → 跳过（完全幂等）
    - 加新 model / 加字段 → 重新部署即可

    注意：create_all **不会做 schema diff**（不会改列类型、不会删列、不会改默认）。
    字段类型变更 / 删列 / 改 FK 行为需要手工 SQL 处理（详见 docs/base/db-schema-sync.md）。
"""
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from src.app.dependencies import get_storage
from src.app.middleware import register_exception_handlers, register_middlewares
from src.app.routes import register_all_routes
from src.infra.config import get_settings
from src.infra.database import close_db, sync_engine
from src.infra.redis import close_redis
from src.models.base import Base


# ============ Schema 同步（幂等） ============

def _sync_schema_blocking() -> None:
    """启动时同步 schema —— 等价于原来的 `alembic upgrade head`，但完全幂等。

    SQLAlchemy 的 create_all：
        - 表不在 → CREATE TABLE
        - 表已存在 → 跳过
        - 不改字段、不删列（这些需要手工 SQL 处理）
    """
    # 这个 import 必须写在这里：触发 src/models/__init__.py 把所有 model
    # 注册到 Base.metadata；写模块顶层会因 import 顺序漏注册。
    import src.models  # noqa: F401  isort:skip

    Base.metadata.create_all(sync_engine)
    table_count = len(Base.metadata.tables)
    print(f"[idpython] schema synced via Base.metadata.create_all ({table_count} tables)")


# ============ Lifespan（应用生命周期） ============

@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动 → 运行 → 关闭。schema 同步在 main() 起 uvicorn 之前已经完成。"""
    print("[idpython] 启动中...")

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
    """`python -m src.main` 入口。

    1. 同步建表（Base.metadata.create_all，幂等）
    2. 起 uvicorn serve
    """
    settings = get_settings()

    # 1. Schema 同步（幂等，可重复跑）
    _sync_schema_blocking()

    # 2. 起 web server
    uvicorn.run(
        app,
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        access_log=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
