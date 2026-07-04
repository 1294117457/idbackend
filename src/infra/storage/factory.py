"""存储工厂 —— 根据 env 选择具体 Adapter

返回类型是 Storage (ABC)，实际对象是 MinIOAdapter / LocalAdapter。
由 Depends(get_storage) 调用一次（@lru_cache 单例），后续请求复用同一实例。

backend 取值：
    - 'minio'   → MinIOAdapter（默认；兼容 AWS S3 协议的 MinIO 服务）
    - 's3'      → 同上（历史别名，保留以兼容旧 .env）
    - 'local'   → LocalAdapter（本地文件系统）
"""
from src.infra.config import get_settings
from src.infra.storage.base import Storage
from src.infra.storage.minio_adapter import build_default_minio_adapter


def create_storage() -> Storage:

    backend = get_settings().storage_backend.lower()

    if backend in ("minio", "s3"):
        return build_default_minio_adapter()

    if backend == "local":
        # 延迟导入，避免开发环境因依赖问题无法启动
        from src.infra.storage.local_adapter import LocalAdapter
        return LocalAdapter(base_dir=get_settings().local_storage_dir)

    raise ValueError(
        f"不支持的 storage_backend: {backend!r}（仅支持 'minio' / 's3' / 'local'）"
    )
