from contextlib import asynccontextmanager
import logging
import os
import shutil
import sys

import uvicorn
from fastapi import FastAPI

from src.app.dependencies import get_storage, set_storage, clear_storage
from src.app.middleware import register_exception_handlers, register_middlewares
from src.app.routes import register_all_routes
from src.infra.config import get_settings
from src.infra.database import close_db, sync_engine
from src.infra.redis import close_redis
from src.models.base import Base

# 配置根日志：输出到 stderr（uvicorn 会收集）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)


# ============ Prometheus 多进程指标目录（必须在 import prometheus_client 之前设置） ============

def _ensure_prometheus_multiproc_dir(settings) -> None:
    """多 worker 模式下，prometheus_client 需要 mmap 目录聚合指标。

    规则：
    - WORKERS == 1：不做任何事（默认进程内模式即可）
    - WORKERS > 1 + PROMETHEUS_MULTIPROC_DIR 已设：启动时清空目录（旧 stale 文件会污染）
    - WORKERS > 1 + PROMETHEUS_MULTIPROC_DIR 未设：警告并自动设为 /tmp/prom_multiproc

    ⚠️ 必须在 import prometheus_client 之前设置环境变量。
    详见 docs/dewu/04-multi-worker-pitfall.md
    """
    if settings.WORKERS <= 1:
        return

    multiproc = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if not multiproc:
        multiproc = "/tmp/prom_multiproc"
        os.environ["PROMETHEUS_MULTIPROC_DIR"] = multiproc
        print(f"[idpython] WORKERS={settings.WORKERS} > 1，自动设置 PROMETHEUS_MULTIPROC_DIR={multiproc}")

    if os.path.exists(multiproc):
        shutil.rmtree(multiproc)
    os.makedirs(multiproc, exist_ok=True)
    print(f"[idpython] Prometheus 多进程目录已就绪: {multiproc}")


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

    # 填充运行时配置缓存（DB > .env）
    try:
        from src.infra.database import AsyncSessionLocal
        from src.infra.config import refresh_cache
        async with AsyncSessionLocal() as db:
            await refresh_cache(db)
        print("[idpython] 运行时配置缓存已加载")
    except Exception as e:
        print(f"[idpython] 运行时配置缓存加载失败（将使用 .env 默认值）: {e}")

    try:
        from src.infra.storage import create_storage
        storage = create_storage()
        set_storage(storage)
        storage.ensure_bucket()
        storage.set_public_read_prefix("avatar")
        # storage.set_public_read_prefix("proof")
        # storage.set_public_read_prefix("policy")
        # storage.set_public_read_prefix("editor")
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

    # 0. Prometheus 多进程指标目录（必须在 import prometheus_client 之前）
    _ensure_prometheus_multiproc_dir(settings)

    # 1. Schema 同步（幂等，可重复跑）
    _sync_schema_blocking()

    # 2. 起 web server（workers>1 时关闭 reload 避免冲突）
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
        workers=settings.WORKERS,
        log_level="info",
    )


if __name__ == "__main__":
    main()
