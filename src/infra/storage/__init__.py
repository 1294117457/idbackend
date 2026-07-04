"""存储抽象层 —— 业务只依赖 Storage 接口，不依赖具体实现

层次：
    Storage (ABC)              ← 接口契约
    ├─ MinIOAdapter           ← MinIO（兼容 AWS S3 协议）
    └─ LocalAdapter           ← 本地文件（开发 / 单测）

设计目标：
- 业务代码里只有 `from src.infra.storage import Storage`
- 通过 Factory（create_storage）拿到具体实现
- 通过 Depends（get_storage）保证应用级单例
"""
from src.infra.storage.base import Storage
from src.infra.storage.minio_adapter import MinIOAdapter
from src.infra.storage.local_adapter import LocalAdapter
from src.infra.storage.factory import create_storage

__all__ = ["Storage", "MinIOAdapter", "LocalAdapter", "create_storage"]
