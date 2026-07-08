##### 1.

```
要实现这个主要业务逻辑，我还需要将文件模块相关的功能完善，
文件相关主要有一个是后台管理学院的政策文件，学生可以在学生端查看下载
然后还有就是刚才说的比如申请材料，或者是用户头像的文件，你觉得这里文件怎么处理呢，
现在用的是seaweedfs，但是我对文件这块了解不多，按照什么标准比如怎么分桶，申请材料存在哪里，政策文件存在哪里，头像存在哪里，我都不太理解，你给我介绍下
```

##### 2.

```
首先就是一个bucket就够对吗，什么情况需要多个bucket呢，然后这里证明材料可能会有很多，多少才需要额外处理呢
然后给我解析下除了bucket还有什么存储的单位呢
```

##### 3.

```
实际就是，主要就是bucket一个存储单位对吗，然后文件就是作为对象直接放在一个bucket，
我后续分bucket可能就是比如按年来分，每年一个新的bucket？

```

##### 4

```
也就是
	id,object_name,
	original_name,file_size，content_type,file_extension,
	file_category,uploader_id,
	created_at,updated_at,deleted_at,is_deleted
	这几个字段是不是其实就够了
，object_name就是在bucket中的对应位置对吗，original_name就是文件上传时的名称对吗

然后bucket具体是那个就是在代码中配置对吗
```

54

```
后端代码中，
   最好是单实例，提升实例的缓存服用率，避免内存空间不够
并发问题下，
   单实例对应处理是提升连接池，以及对应worker多开，
   前提是保证存储桶服务性能够对吗
```





# 文件模块设计文档

> 本文档围绕 `idpython/src/models/file.py` 文件模块的**代码实现**展开，按 **Model → ABC → Adapter → Factory → Depends → Service → Route** 的 7 个层次组织。
>
> 暂不涉及 SeaweedFS / Nginx 等运维侧配置。

---



## 整体架构（一图）

```
┌──────────────────────────────────────────────────────────────────────┐
│  第 1 章  Model 层        file_metadata 表（12 字段）                  │
│  第 2 章  ABC 层         Storage(ABC)（6 个抽象方法）                  │
│  第 3 章  Adapter 层     S3Adapter(Storage)                          │
│  第 4 章  Factory 层     StorageFactory.create() — 读 env 选 Adapter │
│  第 5 章  Depends 层     @lru_cache + Depends(get_storage)           │
│  第 6 章  Service 层     FileService（核心鉴权 + 业务编排）             │
│  第 7 章  Route 层       routes/file.py（8 个接口）                    │
└──────────────────────────────────────────────────────────────────────┘
```

**调用顺序**（一次上传）：

```
.env → Settings → Depends(get_storage) → Factory → Adapter
                                                    ↓
Route (Depends)  →  FileService (构造注入 storage: Storage)  →  ABC 方法
```

---



## 第 1 章 Model 层：`file_metadata` 表

> 本章对应 `src/models/file.py` 中 `FileCategory` 和 `FileMetadata` 两个类。



### 1.1 `FileCategory` 枚举

```python
class FileCategory(str, enum.Enum):
    """文件分类（决定访问控制和 S3 路径前缀）"""
    AVATAR = "AVATAR"        # 头像，公开读，返回直链
    PROOF  = "PROOF"         # 申请证明材料，严格鉴权，预签名 URL
    POLICY = "POLICY"        # 政策文件，宽松鉴权，预签名 URL
```

**为什么用 3 分类**：


| 分类       | 访问方式           | 鉴权           | 典型文件        |
| -------- | -------------- | ------------ | ----------- |
| `AVATAR` | 直链（永久）         | 几乎无          | 头像、Logo     |
| `PROOF`  | 预签名 URL（60min） | 严格：本人/审核员/超管 | 成绩单、证书、论文   |
| `POLICY` | 预签名 URL（60min） | 宽松：已登录用户     | 保研政策文件、规章制度 |




### 1.2 `FileMetadata` 模型（12 字段）

```python
class FileMetadata(Base, TimestampMixin):
    """文件元数据表"""
    __tablename__ = "file_metadata"

    # ---- 定位 ----
    object_name:     Mapped[str]            # S3 key，如 proof/2025/123/abc.pdf
    # ---- 原始信息 ----
    original_name:   Mapped[str]            # 用户上传时的原始文件名（含中文）
    file_size:       Mapped[int]            # 字节数
    content_type:    Mapped[Optional[str]]  # MIME，如 application/pdf
    file_extension:  Mapped[Optional[str]]  # 后缀，不含点
    # ---- 鉴权核心 ----
    file_category:   Mapped[FileCategory]   # 决定鉴权分支和 S3 路径前缀
    file_purpose:    Mapped[Optional[str]]  # 业务描述
    upload_user_id:  Mapped[int]            # 上传人
    # ---- 软删除 ----
    is_deleted:      Mapped[bool]           # 默认 False
    delete_time:     Mapped[Optional[str]]  # 软删除时间
    # ---- 时间戳（来自 TimestampMixin）----
    created_at: ...
    updated_at: ...
```



### 1.3 字段速查


| 字段                          | 含义                                                | 谁填                   |
| --------------------------- | ------------------------------------------------- | -------------------- |
| `id`                        | 主键                                                | DB 自动                |
| `object_name`               | S3 key：`{category}/{year}/{user_id}/{uuid}.{ext}` | 系统生成                 |
| `original_name`             | 用户原文件名，如 `成绩单.pdf`                                | 用户上传                 |
| `file_size`                 | 字节数                                               | 系统读                  |
| `content_type`              | MIME                                              | 系统读/推断               |
| `file_extension`            | 后缀（不加点）                                           | 从 `original_name` 提取 |
| `file_category`             | 分类，**决定鉴权分支**                                     | 业务路由                 |
| `file_purpose`              | 业务描述（`成绩单`、`身份证正面`）                               | 业务调用                 |
| `upload_user_id`            | 上传人                                               | 从 JWT 取              |
| `created_at` / `updated_at` | 时间戳                                               | DB 自动                |
| `delete_time`               | 软删除时间                                             | 删除时                  |
| `is_deleted`                | 软删除标志                                             | 默认 False             |




### 1.4 索引设计

```python
__table_args__ = (
    Index("ix_file_category_deleted", "file_category", "is_deleted"),
)

# 此外靠 column 上的 index=True 自动建了 4 个单字段索引：
#   ix_file_metadata_object_name
#   ix_file_metadata_file_category
#   ix_file_metadata_upload_user_id
#   ix_file_metadata_is_deleted
```

**索引用途**：


| 索引                               | 加速的查询                  |
| -------------------------------- | ---------------------- |
| `object_name`                    | 通过 S3 key 反查元数据        |
| `file_category`                  | "列出所有 PROOF 类型文件"      |
| `upload_user_id`                 | "我上传的所有文件"             |
| `is_deleted`                     | 过滤未删除文件                |
| `(file_category, is_deleted)` 组合 | "列出未删除的 PROOF 文件"（最常用） |




### 1.5 数据库建表 SQL

```sql
CREATE TABLE file_metadata (
    id              INTEGER         PRIMARY KEY AUTOINCREMENT,
    object_name     VARCHAR(255)    NOT NULL,
    original_name   VARCHAR(255)    NOT NULL,
    file_size       INTEGER         NOT NULL,
    content_type    VARCHAR(100),
    file_extension  VARCHAR(10),
    file_category   VARCHAR(20)     NOT NULL,    -- AVATAR / PROOF / POLICY
    file_purpose    VARCHAR(200),
    upload_user_id  INTEGER         NOT NULL,
    created_at      VARCHAR(50)     NOT NULL,
    updated_at      VARCHAR(50)     NOT NULL,
    deleted_at      VARCHAR(50),
    is_deleted      BOOLEAN         NOT NULL DEFAULT FALSE
);

CREATE INDEX ix_file_metadata_object_name    ON file_metadata (object_name);
CREATE INDEX ix_file_metadata_file_category   ON file_metadata (file_category);
CREATE INDEX ix_file_metadata_upload_user_id  ON file_metadata (upload_user_id);
CREATE INDEX ix_file_metadata_is_deleted      ON file_metadata (is_deleted);
CREATE INDEX ix_file_metadata_cat_deleted     ON file_metadata (file_category, is_deleted);
```

> **相对原版改动**（如果是从旧 model 迁过来）：
>
> - 删 `bucket_name`（配置项，不应进 DB）
> - 删 `object_name` 的 `unique` 约束（同时记录 + 历史记录可能相同，加索引即可）
> - `file_category` 改用 SQLAlchemy `Enum`（长度 50→20）
> - 加 3 个单字段索引 + 1 个组合索引

---



## 第 2 章 ABC 层：`Storage(ABC)`

> **设计目标**：把"上传/下载/删除/获取 URL" 这些操作变成一份**契约**，业务只依赖这个契约，不依赖任何具体实现。



### 2.1 抽象基类完整定义

**文件**：`src/infra/storage/base.py`（**新文件**）

```python
"""存储抽象基类 —— 所有存储后端必须实现的契约"""
from abc import ABC, abstractmethod
from typing import BinaryIO


class Storage(ABC):
    """文件存储的统一接口"""

    # ============= 业务操作 =============

    @abstractmethod
    async def upload(
        self,
        file_obj: BinaryIO,
        key: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        """
        上传文件

        Args:
            file_obj:     类文件对象（如 UploadFile.file、BytesIO）
            key:          对象 key，如 "proof/2025/123/abc.pdf"
            content_type: MIME

        Returns:
            最终的访问标识（一般是 key 本身）
        """
        raise NotImplementedError

    @abstractmethod
    async def download(self, key: str) -> bytes:
        """下载文件，返回二进制字节"""
        raise NotImplementedError

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """物理删除文件"""
        raise NotImplementedError

    @abstractmethod
    def get_access_url(self, key: str, expiry: int = 3600) -> str:
        """
        生成前端可访问的 URL

        - AVATAR：直链（需 Nginx 开放 /avatar/ 公开访问）
        - PROOF / POLICY：预签名 URL
        """
        raise NotImplementedError

    # ============= 生命周期 =============

    @abstractmethod
    def ensure_bucket(self) -> None:
        """启动时确保 bucket 存在（幂等）"""
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        """释放底层连接（boto3 client 等）"""
        raise NotImplementedError
```



### 2.2 为什么是 6 个方法


| 方法               | 分类       | 何时调          |
| ---------------- | -------- | ------------ |
| `upload`         | 业务       | 每次上传         |
| `download`       | 业务       | 服务端代下载       |
| `delete`         | 业务       | 后台清理（物理删除）   |
| `get_access_url` | 业务       | 拿预览 URL      |
| `ensure_bucket`  | **生命周期** | lifespan 启动时 |
| `close`          | **生命周期** | lifespan 关闭时 |


`ensure_bucket` **为什么必须在 ABC 里**：

- 业务侧需要统一入口：`storage.ensure_bucket()`（一行通用）
- 如果不放 ABC，业务就得 `if isinstance(s, S3Adapter): ...`——加新 Adapter 必改业务代码
- 每个存储的"幂等初始化"语义不同：S3 走 API 检查 + create，Local 走 `mkdir`——但入口统一



### 2.3 业务侧的调用方式

```python
# 业务代码永远不 import Adapter，只 import ABC
from src.infra.storage.base import Storage

class FileService:
    def __init__(self, db, storage: Storage):
        self._storage = storage

    async def upload(self, file_data, key, content_type):
        # 调 ABC 方法，运行时动态分派到具体 Adapter
        await self._storage.upload(
            file_obj=io.BytesIO(file_data),
            key=key,
            content_type=content_type,
        )
```

---



## 第 3 章 Adapter 层：`S3Adapter`

> **本章对应**：当前 `src/infra/s3.py` 中的 `S3Client`。
> **重构目标**：把 `S3Client` 改名为 `S3Adapter`，并让它继承 `Storage(ABC)`。



### 3.1 `S3Adapter` 完整代码

**文件**：`src/infra/storage/s3_adapter.py`（**新文件 / 或把现有** `src/infra/s3.py` **改名**）

```python
"""SeaweedFS / S3 实现（继承 Storage ABC）"""
from typing import BinaryIO
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from src.infra.storage.base import Storage


class S3Adapter(Storage):
    """S3 兼容对象存储实现（适配 SeaweedFS / 阿里 OSS / AWS S3）"""

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
    ):
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="us-east-1",
            config=Config(signature_version="s3v4"),
        )
        # 头像直链前缀（公开读，绕过签名）
        self._public_url = endpoint.rstrip("/")

    # ============= 业务操作 =============

    async def upload(
        self,
        file_obj: BinaryIO,
        key: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=file_obj.read(),
            ContentType=content_type,
        )
        return key

    async def download(self, key: str) -> bytes:
        resp = self._client.get_object(Bucket=self._bucket, Key=key)
        return resp["Body"].read()

    async def delete(self, key: str) -> bool:
        self._client.delete_object(Bucket=self._bucket, Key=key)
        return True

    def get_access_url(self, key: str, expiry: int = 3600) -> str:
        """
        生成预签名 URL（PROOF / POLICY / AVATAR 都能用）

        SeaweedFS 默认对 S3 GET 强制签名，所以这里统一返回预签名 URL。
        如需 AVATAR 走直链（永久公开），业务层可特判 key 前缀。
        """
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expiry,
        )

    # ============= 生命周期 =============

    def ensure_bucket(self) -> None:
        """S3 启动时：检查 bucket，不存在就建"""
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self._bucket)

    def close(self) -> None:
        """释放 boto3 client"""
        self._client.close()
```



### 3.2 方法签名映射（老 `S3Client` → 新 `S3Adapter`）


| 老 `S3Client`                                            | 新 `S3Adapter`                                   | 改动点           |
| ------------------------------------------------------- | ----------------------------------------------- | ------------- |
| `def upload_file(file_data, object_name, content_type)` | `async def upload(file_obj, key, content_type)` | 同步→异步，参数名变    |
| `def download_file(object_name)`                        | `async def download(key)`                       | 同步→异步，参数名变    |
| `def delete_file(object_name)`                          | `async def delete(key)`                         | 同步→异步，参数名变    |
| `def get_presigned_url(object_name, expiry)`            | `def get_access_url(key, expiry)`               | 改名            |
| `def ensure_bucket(self)`                               | `def ensure_bucket(self)`                       | **不变**（签名一致）  |
| （无）                                                     | `def close(self)`                               | **新增**        |
| `class S3Client:`                                       | `class S3Adapter(Storage):`                     | 继承 ABC        |
| `@lru_cache get_s3_client()`                            | 删除                                              | 由 Depends 层负责 |




### 3.3 老 `S3Client` 完整实现（参考当前 `src/infra/s3.py`）

如果暂时不想重构，可以保留现状（`S3Client` 不继承 ABC），但**老 API**如下：

```python
class S3Client:
    """SeaweedFS S3 兼容客户端（当前实现）"""

    def __init__(self, endpoint, access_key, secret_key, bucket):
        self.bucket = bucket
        self.client = boto3.client("s3", endpoint_url=endpoint, ...)
        self.public_url = endpoint.rstrip("/")

    def ensure_bucket(self):          # head_bucket + create_bucket
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self.client.create_bucket(Bucket=self.bucket)

    def upload_file(self, file_data, object_name, content_type="application/octet-stream"):
        self.client.put_object(Bucket=self.bucket, Key=object_name,
                               Body=file_data, ContentType=content_type)
        return object_name

    def get_presigned_url(self, object_name, expiry=3600):
        return self.client.generate_presigned_url("get_object", ...)

    def download_file(self, object_name):
        return self.client.get_object(Bucket=self.bucket, Key=object_name)["Body"].read()

    def delete_file(self, object_name):
        self.client.delete_object(Bucket=self.bucket, Key=object_name)
        return True


@lru_cache
def get_s3_client() -> S3Client:
    return S3Client(
        endpoint=settings.S3_ENDPOINT,
        access_key=settings.S3_ACCESS_KEY,
        secret_key=settings.S3_SECRET_KEY,
        bucket=settings.S3_BUCKET,
    )
```



### 3.4 `LocalAdapter`（可选，便于本地开发）

```python
"""本地文件系统实现（开发 / 单测用）"""
import os
from typing import BinaryIO
from src.infra.storage.base import Storage


class LocalAdapter(Storage):
    def __init__(self, base_dir: str):
        self._base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)

    async def upload(self, file_obj, key, content_type="application/octet-stream"):
        path = os.path.join(self._base_dir, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(file_obj.read())
        return key

    async def download(self, key):
        with open(os.path.join(self._base_dir, key), "rb") as f:
            return f.read()

    async def delete(self, key):
        path = os.path.join(self._base_dir, key)
        if os.path.exists(path):
            os.remove(path)
        return True

    def get_access_url(self, key, expiry=3600):
        # 本地存储走 Nginx 静态目录
        return f"/static/{key}"

    def ensure_bucket(self):
        os.makedirs(self._base_dir, exist_ok=True)

    def close(self):
        pass
```

---



## 第 4 章 Factory 层：`StorageFactory`

> **设计目标**：根据 `env.STORAGE_BACKEND`，返回对应 Adapter；返回类型是 `Storage`（ABC），实际是子类型。



### 4.1 `Settings` 加 1 个字段

**文件**：`src/core/config.py`

```python
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # ... 其它字段 ...

    # ============= 存储后端选择 =============
    storage_backend:    str = Field(default="s3", env="STORAGE_BACKEND")
    local_storage_dir:  str = Field(default="./storage", env="LOCAL_STORAGE_DIR")

    # ============= S3 配置 =============
    S3_ENDPOINT:   str = "http://223.109.49.63:8333"
    S3_ACCESS_KEY: str = "idproject"
    S3_SECRET_KEY: str = "zhouchenhui"
    S3_BUCKET:     str = "idproject"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
```



### 4.2 `.env` 切后端

```bash
# 生产
STORAGE_BACKEND=s3

# 开发（不依赖 SeaweedFS）
STORAGE_BACKEND=local
```



### 4.3 `StorageFactory` 完整代码

**文件**：`src/infra/storage/factory.py`（**新文件**）

```python
"""存储工厂 —— 根据 env 配置选择 Adapter"""
from src.core.config import settings
from src.infra.storage.base import Storage
from src.infra.storage.s3_adapter import S3Adapter


def create_storage() -> Storage:
    """
    根据 settings.storage_backend 返回对应 Adapter

    返回类型是抽象基类 Storage，实际对象是 S3Adapter 或 LocalAdapter
    """
    backend = settings.storage_backend

    if backend == "s3":
        return S3Adapter(
            endpoint=settings.S3_ENDPOINT,
            access_key=settings.S3_ACCESS_KEY,
            secret_key=settings.S3_SECRET_KEY,
            bucket=settings.S3_BUCKET,
        )

    if backend == "local":
        # 仅在本地开发 / 单测时启用
        from src.infra.storage.local_adapter import LocalAdapter
        return LocalAdapter(base_dir=settings.local_storage_dir)

    raise ValueError(f"不支持的 storage_backend: {backend}")
```



### 4.4 决策图

```
        settings.storage_backend
                 │
   ┌─────────────┴─────────────┐
   │                           │
  "s3"                       "local"
   │                           │
   ▼                           ▼
S3Adapter(...)          LocalAdapter(...)
(boto3 client)          (本地文件 IO)
   │                           │
   └─────────────┬─────────────┘
                 ▼
        return: Storage
      (类型是 ABC，实际是 Adapter)
```

---



## 第 5 章 Depends 层：`@lru_cache + Depends`

> **设计目标**：把 `get_s3_client()` 这个**全局 getter**，升级为 **FastAPI 依赖注入**——业务侧 `service = Depends(get_file_service)` 一行拿到完整服务。



### 5.1 `get_storage` 依赖（lru_cache 单例）

**文件**：`src/app/dependencies.py`（**新文件 / 或现有** `deps.py` **加 get_storage**）

```python
"""FastAPI 依赖注入 —— Storage 单例"""
from functools import lru_cache

from src.infra.storage.factory import create_storage
from src.infra.storage.base import Storage


@lru_cache(maxsize=1)
def get_storage() -> Storage:
    """
    FastAPI 依赖：返回全局唯一 Storage 实例

    - 第一次调用时执行 StorageFactory.create()（耗时 1 次）
    - 后续调用直接返回缓存对象
    - 类型注解是 Storage（ABC），运行时是 S3Adapter
    """
    return create_storage()
```

**两件事的合并**：

1. **单例保证**：`@lru_cache(maxsize=1)` → 整个应用一个 `Storage` 实例
2. **FastAPI 注入**：被 `Depends(get_storage)` 注入到 route



### 5.2 `get_file_service` 业务依赖

**继续在** `dependencies.py` **中**：

```python
from src.app.deps import get_db           # 你现有的 db 依赖
from src.services.file_service import FileService


def get_file_service(
    db = Depends(get_db),                          # 数据库 session（每请求新建）
    storage: Storage = Depends(get_storage),       # 存储（应用级单例）
) -> FileService:
    """把 db + storage 组装成 FileService，注入到 route"""
    return FileService(db=db, storage=storage)
```



### 5.3 两种注入方式对比


| 方式                 | 代码                                                             | 适用场景           |
| ------------------ | -------------------------------------------------------------- | -------------- |
| **A：**`@lru_cache` | `@lru_cache def get_storage() -> Storage: ...`                 | 起步、无状态客户端      |
| **B：**`app.state`  | `def get_storage(request: Request): request.app.state.storage` | 生产、需测试 mock 覆盖 |


**方式 A（推荐起步用）**：

```python
@lru_cache(maxsize=1)
def get_storage() -> Storage:
    return create_storage()
```

**方式 B（生产推荐，可被** `app.dependency_overrides` **替换）**：

```python
from fastapi import Request

def get_storage(request: Request) -> Storage:
    if not hasattr(request.app.state, "storage"):
        request.app.state.storage = create_storage()
    return request.app.state.storage
```

测试时用 `app.dependency_overrides[get_storage] = lambda: MockStorage()` 替换——**完全不需要 patch boto3**。

---



## 第 6 章 Service 层：`FileService`

> **设计目标**：把"上传 / 预览 / 下载 / 删除 / 搜索"这些业务操作集中在一个 Service，**鉴权逻辑也在这里**。



### 6.1 当前实现（基于老 `S3Client`）



#### 6.1.1 模块级辅助

```python
# src/services/file_service.py

# 允许查看 PROOF 类型文件的权限码
PROOF_VIEW_PERMISSION = "application:review"


class FileAuthError(Exception):
    """文件鉴权失败"""
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _build_object_name(category: FileCategory, original_name: str, user_id: int) -> str:
    """
    生成 S3 object_name
    路径模板：{category}/{year}/{user_id}/{uuid}.{ext}
    """
    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if ext and len(ext) > 10:
        ext = ext[:10]

    unique_id = uuid.uuid4().hex
    year = datetime.utcnow().year
    category_prefix = category.value.lower()

    if ext:
        return f"{category_prefix}/{year}/{user_id}/{unique_id}.{ext}"
    return f"{category_prefix}/{year}/{user_id}/{unique_id}"
```

**举例**：


| 调用                  | 输出                             |
| ------------------- | ------------------------------ |
| 用户 123 + 成绩单.pdf    | `proof/2025/123/abc123def.pdf` |
| 用户 456 + avatar.jpg | `avatar/2025/456/xxx.jpg`      |




#### 6.1.2 PROOF 鉴权（核心：3 表 JOIN）

**关系链**：

```
applications (申请人 + 申请本身)
   ↑ 1:N
score_application_proofs (证明材料列表)
   ↑ N:1
file_metadata (具体的证明材料文件)
```

**关键代码**：

```python
async def _check_proof_access(
    db: AsyncSession,
    file_meta: FileMetadata,
    user_id: int,
    user_permissions: List[str],
) -> None:
    """PROOF 类型文件鉴权：通过 JOIN 反查文件属于哪个申请人"""
    has_star = "*" in user_permissions
    has_review = PROOF_VIEW_PERMISSION in user_permissions

    if has_star:
        return  # 超管直接放行

    # 3 表 JOIN 反查
    result = await db.execute(
        select(Application.user_id)
        .join(ApplicationProof, ApplicationProof.application_id == Application.id)
        .where(ApplicationProof.proof_file_id == file_meta.id)
    )
    application_user_id = result.scalar_one_or_none()

    if application_user_id is None:
        raise FileAuthError("not_found", "文件未关联到任何申请")

    if application_user_id == user_id:
        return  # 本人

    if has_review:
        return  # 审核员

    raise FileAuthError("forbidden", "无权访问此文件")
```



#### 6.1.3 上传

```python
@staticmethod
async def upload_file(
    db, file_data, original_name, content_type,
    user_id, category="PROOF", purpose="",
) -> Tuple[FileMetadata, str]:
    """通用文件上传"""
    s3_client = get_s3_client()                   # 老写法：直接 import getter
    file_category = FileCategory(category)

    # 1. 生成 object_name
    object_name = _build_object_name(file_category, original_name, user_id)
    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""

    # 2. 上传到 S3
    s3_client.upload_file(file_data, object_name, content_type)

    # 3. 写 file_metadata
    file_meta = FileMetadata(
        object_name=object_name,
        original_name=original_name,
        file_size=len(file_data),
        content_type=content_type,
        file_extension=ext,
        file_category=file_category,
        file_purpose=purpose,
        upload_user_id=user_id,
    )
    db.add(file_meta)
    await db.commit()
    await db.refresh(file_meta)

    # 4. 返回访问 URL
    preview_url = s3_client.get_presigned_url(object_name)
    return file_meta, preview_url


@staticmethod
async def upload_avatar(
    db, file_data, user_id, content_type,
) -> Tuple[FileMetadata, str]:
    """上传头像"""
    s3_client = get_s3_client()
    object_name = _build_object_name(
        FileCategory.AVATAR, f"avatar_{user_id}.jpg", user_id
    )
    s3_client.upload_file(file_data, object_name, content_type)

    file_meta = FileMetadata(
        object_name=object_name,
        original_name=f"avatar_{user_id}.jpg",
        file_size=len(file_data),
        content_type=content_type,
        file_extension="jpg",
        file_category=FileCategory.AVATAR,
        file_purpose="avatar",
        upload_user_id=user_id,
    )
    db.add(file_meta)
    await db.commit()
    await db.refresh(file_meta)

    # 头像返回直链（公开读）
    return file_meta, f"{s3_client.public_url}/{object_name}"
```



#### 6.1.4 预览 URL（核心鉴权入口）

```python
@staticmethod
async def get_preview_url(
    db, file_id, user_id, user_permissions=None,
) -> Optional[str]:
    """按 file_category 分支"""
    file_meta = await FileService.get_file_by_id(db, file_id)
    if not file_meta:
        return None

    s3_client = get_s3_client()

    # AVATAR：直链
    if file_meta.file_category == FileCategory.AVATAR:
        return f"{s3_client.public_url}/{file_meta.object_name}"

    # POLICY：已登录即返回预签名
    if file_meta.file_category == FileCategory.POLICY:
        return s3_client.get_presigned_url(file_meta.object_name)

    # PROOF：鉴权 + 预签名
    if file_meta.file_category == FileCategory.PROOF:
        await _check_proof_access(db, file_meta, user_id, user_permissions or [])
        return s3_client.get_presigned_url(file_meta.object_name)

    return None
```



#### 6.1.5 下载

```python
@staticmethod
async def download_file(
    db, file_id, user_id, user_permissions=None,
) -> Optional[Tuple[bytes, str, str]]:
    """下载文件（带鉴权）"""
    file_meta = await FileService.get_file_by_id(db, file_id)
    if not file_meta:
        return None

    # PROOF 也走鉴权（防止跳过 preview 直接 download）
    if file_meta.file_category == FileCategory.PROOF:
        await _check_proof_access(db, file_meta, user_id, user_permissions or [])

    s3_client = get_s3_client()
    file_data = s3_client.download_file(file_meta.object_name)
    return file_data, file_meta.content_type or "application/octet-stream", file_meta.original_name
```



#### 6.1.6 删除（软删）

```python
@staticmethod
async def delete_file(
    db, file_id, user_id, user_permissions=None,
) -> Tuple[bool, str]:
    """本人 / 超管 可删"""
    file_meta = await FileService.get_file_by_id(db, file_id)
    if not file_meta:
        return False, "not_found"

    is_owner = file_meta.upload_user_id == user_id
    is_admin = user_permissions and "*" in user_permissions
    if not (is_owner or is_admin):
        return False, "forbidden"

    file_meta.is_deleted = True
    file_meta.delete_time = datetime.utcnow().isoformat()
    await db.commit()
    return True, ""
```



#### 6.1.7 搜索

```python
@staticmethod
async def search_files(
    db, user_id=None, category=None, filename_keyword=None, page=1, size=20,
) -> Tuple[List[FileMetadata], int]:
    """分页 + 条件"""
    conditions = [FileMetadata.is_deleted == False]
    if user_id:
        conditions.append(FileMetadata.upload_user_id == user_id)
    if category:
        conditions.append(FileMetadata.file_category == category)
    if filename_keyword:
        conditions.append(FileMetadata.original_name.ilike(f"%{filename_keyword}%"))

    # 计数
    total = (await db.execute(
        select(func.count()).select_from(FileMetadata).where(*conditions)
    )).scalar() or 0

    # 分页
    files = (await db.execute(
        select(FileMetadata).where(*conditions)
        .order_by(FileMetadata.created_at.desc())
        .offset((page - 1) * size).limit(size)
    )).scalars().all()

    return list(files), total
```



### 6.2 鉴权决策表


| 文件类型                      | AVATAR | POLICY  | PROOF   |
| ------------------------- | ------ | ------- | ------- |
| 已登录学生看自己头像                | ✅ 直链   | —       | —       |
| 已登录学生看别人头像                | ✅ 直链   | —       | —       |
| 未登录用户                     | ✅ 直链   | ❌ 路由层拦截 | ❌ 路由层拦截 |
| 已登录学生看 POLICY             | —      | ✅ 预签名   | —       |
| 已登录学生看别人的 PROOF           | —      | —       | ❌ 403   |
| 本人看自己的 PROOF              | —      | —       | ✅ 预签名   |
| 审核员（`application:review`） | —      | —       | ✅ 预签名   |
| 超级管理员（`*`）                | —      | ✅       | ✅       |




### 6.3 重构后的 `FileService`（基于 ABC + 注入）

> **目标版本**：把 `from src.infra.s3 import get_s3_client` 全删，改成 `__init__(db, storage: Storage)`。

```python
"""文件服务 —— 改成依赖注入"""
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List, Tuple
from datetime import datetime
import uuid
import io

from src.infra.storage.base import Storage             # ← 只 import ABC
from src.models import FileMetadata, FileCategory, ApplicationProof, Application


# 模块级辅助不变
PROOF_VIEW_PERMISSION = "application:review"


class FileAuthError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)


def _build_object_name(category, original_name, user_id):
    # 同 6.1.1 —— 纯字符串拼接，不依赖存储
    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if ext and len(ext) > 10:
        ext = ext[:10]
    unique_id = uuid.uuid4().hex
    year = datetime.utcnow().year
    category_prefix = category.value.lower()
    if ext:
        return f"{category_prefix}/{year}/{user_id}/{unique_id}.{ext}"
    return f"{category_prefix}/{year}/{user_id}/{unique_id}"


class FileService:
    """
    改 3 处：
    1. 构造参数加 storage: Storage
    2. 删掉所有 `from src.infra.s3 import get_s3_client`
    3. 所有 `s3_client = get_s3_client()` 改成 `self._storage`
    """

    def __init__(self, db: AsyncSession, storage: Storage):
        self._db = db
        self._storage = storage                     # ← 注入 ABC

    # ----- 上传 -----
    async def upload_file(self, file_data, original_name, content_type,
                          user_id, category="PROOF", purpose=""):
        file_category = FileCategory(category)
        object_name = _build_object_name(file_category, original_name, user_id)
        ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""

        # 通过 ABC 上传（不关心是 S3 还是 local）
        await self._storage.upload(
            file_obj=io.BytesIO(file_data),
            key=object_name,
            content_type=content_type,
        )

        file_meta = FileMetadata(
            object_name=object_name,
            original_name=original_name,
            file_size=len(file_data),
            content_type=content_type,
            file_extension=ext,
            file_category=file_category,
            file_purpose=purpose,
            upload_user_id=user_id,
        )
        self._db.add(file_meta)
        await self._db.commit()
        await self._db.refresh(file_meta)

        # 通过 ABC 拿 URL
        access_url = self._storage.get_access_url(object_name)
        return file_meta, access_url

    # ----- 预览 -----
    async def get_preview_url(self, file_id, user_id, user_permissions=None):
        file_meta = await self._get_file(file_id)
        if not file_meta:
            return None

        if file_meta.file_category == FileCategory.AVATAR:
            return self._storage.get_access_url(file_meta.object_name)

        if file_meta.file_category == FileCategory.POLICY:
            return self._storage.get_access_url(file_meta.object_name)

        if file_meta.file_category == FileCategory.PROOF:
            await self._check_proof_access(file_meta, user_id, user_permissions or [])
            return self._storage.get_access_url(file_meta.object_name)

        return None

    # ----- 下载 -----
    async def download_file(self, file_id, user_id, user_permissions=None):
        file_meta = await self._get_file(file_id)
        if not file_meta:
            return None
        if file_meta.file_category == FileCategory.PROOF:
            await self._check_proof_access(file_meta, user_id, user_permissions or [])

        file_data = await self._storage.download(file_meta.object_name)
        return file_data, file_meta.content_type, file_meta.original_name

    # ----- 删除（软删）-----
    async def delete_file(self, file_id, user_id, user_permissions=None):
        file_meta = await self._get_file(file_id)
        if not file_meta:
            return False, "not_found"
        is_owner = file_meta.upload_user_id == user_id
        is_admin = user_permissions and "*" in user_permissions
        if not (is_owner or is_admin):
            return False, "forbidden"
        file_meta.is_deleted = True
        file_meta.delete_time = datetime.utcnow().isoformat()
        await self._db.commit()
        return True, ""

    # ----- 内部辅助 -----
    async def _get_file(self, file_id):
        result = await self._db.execute(
            select(FileMetadata).where(
                FileMetadata.id == file_id,
                FileMetadata.is_deleted == False,
            )
        )
        return result.scalar_one_or_none()

    async def _check_proof_access(self, file_meta, user_id, user_permissions):
        # 逻辑同 6.1.2，把 db 换成 self._db
        ...
```

---



## 第 7 章 Route 层：`routes/file.py`



### 7.1 接口清单


| 方法       | 路径                                      | 说明      | 鉴权            |
| -------- | --------------------------------------- | ------- | ------------- |
| `POST`   | `/api/file/upload`                      | 通用上传    | 已登录           |
| `POST`   | `/api/file/avatar`                      | 上传头像    | 已登录           |
| `GET`    | `/api/file/{id}/preview`                | 拿预览 URL | 按 category 分支 |
| `GET`    | `/api/file/{id}/download`               | 实际下载    | 按 category 分支 |
| `GET`    | `/api/file/search`                      | 分页搜索    | 已登录           |
| `GET`    | `/api/file/{id}`                        | 文件元信息   | 已登录           |
| `DELETE` | `/api/file/{id}`                        | 软删除     | 本人 / 超管       |
| `GET`    | `/api/file/proof/list/{application_id}` | 申请证明列表  | 申请相关人         |
| `POST`   | `/api/file/proof/{id}/approve`          | 审核通过    | 审核员           |
| `POST`   | `/api/file/proof/{id}/reject`           | 驳回      | 审核员           |




### 7.2 当前实现（基于老 Service）

```python
"""文件路由"""
from fastapi import APIRouter, Depends, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import io

from src.app.deps import get_db
from src.app.context import get_user_id, get_user_permissions
from src.app import response as R
from src.services import FileService


router = APIRouter(prefix="/api/file", tags=["文件"])


def _check_file_size(content: bytes) -> None:
    settings = get_settings()
    if len(content) > settings.MAX_FILE_SIZE:
        raise R.HTTPException(413, f"文件大小不能超过 {settings.MAX_FILE_SIZE // (1024*1024)}MB")


# ============ 上传 ============

@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    fileCategory: str = Query("PROOF"),
    filePurpose: str = Query("加分证明材料"),
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    _check_file_size(content)
    file_meta, url = await FileService.upload_file(
        db=db,
        file_data=content,
        original_name=file.filename or "unnamed",
        content_type=file.content_type or "application/octet-stream",
        user_id=get_user_id(),
        category=fileCategory,
        purpose=filePurpose,
    )
    return R.success_resp({"fileId": file_meta.id, "url": url})


@router.post("/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    _check_file_size(content)
    file_meta, url = await FileService.upload_avatar(
        db=db,
        file_data=content,
        user_id=get_user_id(),
        content_type=file.content_type or "image/jpeg",
    )
    return R.success_resp({"fileId": file_meta.id, "url": url})


# ============ 预览 ============

@router.get("/{file_id}/preview")
async def get_preview_url(
    file_id: int,
    expiryMinutes: int = Query(60),
    db: AsyncSession = Depends(get_db),
):
    try:
        url = await FileService.get_preview_url(
            db, file_id,
            user_id=get_user_id(),
            user_permissions=get_user_permissions(),
        )
    except FileService.FileAuthError as e:
        return R.forbidden_resp(e.message)
    if not url:
        return R.not_found_resp("文件不存在")
    return R.success_resp(url)


# ============ 下载 ============

@router.get("/{file_id}/download")
async def download_file(
    file_id: int,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await FileService.download_file(
            db, file_id,
            user_id=get_user_id(),
            user_permissions=get_user_permissions(),
        )
    except FileService.FileAuthError as e:
        return R.forbidden_resp(e.message)
    if not result:
        return R.not_found_resp("文件不存在")

    file_data, content_type, original_name = result
    from urllib.parse import quote
    encoded_name = quote(original_name, safe='')
    return StreamingResponse(
        io.BytesIO(file_data),
        media_type=content_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"},
    )


# ============ 搜索 / 元信息 / 删除 ============
# （与上面模式相同，详见 src/app/routes/file.py）
```



### 7.3 重构后的 Route（基于 Depends 注入）

**改动点**：把 `FileService.xxx(db, ...)` 改成 `service.xxx(...)`，`service` 来自 `Depends(get_file_service)`。

```python
"""文件路由 —— 改成依赖注入"""
from fastapi import APIRouter, Depends, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.deps import get_db
from src.app.context import get_user_id, get_user_permissions
from src.app.dependencies import get_file_service     # ← 改：注入业务 Service
from src.app import response as R
from src.services.file_service import FileService


router = APIRouter(prefix="/api/file", tags=["文件"])


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    fileCategory: str = Query("PROOF"),
    filePurpose: str = Query("加分证明材料"),
    db: AsyncSession = Depends(get_db),
    service: FileService = Depends(get_file_service),     # ← 注入业务 Service
):
    """上传文件"""
    content = await file.read()
    file_meta, url = await service.upload_file(
        file_data=content,
        original_name=file.filename or "unnamed",
        content_type=file.content_type or "application/octet-stream",
        user_id=get_user_id(),
        category=fileCategory,
        purpose=filePurpose,
    )
    return R.success_resp({"fileId": file_meta.id, "url": url})


@router.get("/{file_id}/preview")
async def get_preview_url(
    file_id: int,
    expiryMinutes: int = Query(60),
    db: AsyncSession = Depends(get_db),
    service: FileService = Depends(get_file_service),
):
    try:
        url = await service.get_preview_url(
            file_id,
            user_id=get_user_id(),
            user_permissions=get_user_permissions(),
        )
    except FileService.FileAuthError as e:
        return R.forbidden_resp(e.message)
    if not url:
        return R.not_found_resp("文件不存在")
    return R.success_resp(url)
```

---



## 附录 A：完整调用链（一次"上传证明材料"）

```
.env: STORAGE_BACKEND=s3
                ↓
Settings.storage_backend == "s3"
                ↓
[ lifespan 启动 ]                    ← FastAPI 应用启动钩子
   get_storage() → @lru_cache 单例
       ↓
   StorageFactory.create()           ← 读 env，决策
       ↓
   S3Adapter(boto3 client)
       ↓
   storage.ensure_bucket()           ← 调 ABC 方法，动态分派到 S3Adapter
       ↓
   boto3: head_bucket / create_bucket
                ↓
[ 业务请求到达 ]
   POST /api/file/upload
       ↓
   @router.upload_file(
       service: FileService = Depends(get_file_service)
   )
       ↓
   get_file_service(
       db = Depends(get_db),
       storage: Storage = Depends(get_storage)        ← 注入
   )
       ↓
   FileService(db, storage=self._storage)
       ↓
   service.upload_file(...)
       ↓
   self._storage.upload(BytesIO(content), key, content_type)   ← 调 ABC
       ↓
   S3Adapter.upload() → boto3 put_object
       ↓
   INSERT INTO file_metadata (id, object_name, file_category=PROOF, ...)
       ↓
   self._storage.get_access_url(key) → boto3 generate_presigned_url
       ↓
   返回 { "fileId": 100, "url": "http://...?...signature=..." }
```

**业务代码中**：

- `routes/file.py` 不知道有 `S3Adapter`（只 import `FileService`）
- `FileService` 不知道有 `boto3`（只 import `Storage(ABC)`）
- 只有 `S3Adapter` 知道 boto3 的存在

---



## 附录 B：迁移 checklist

如果你要把当前代码升级到 4 层架构：

- [ ] **DB 层**：写 Alembic 迁移（删 `bucket_name`、改 `file_category` 为 Enum、加索引）
- [ ] **Model 层**：替换 `src/models/file.py`
- [ ] **新增 ABC 层**：建 `src/infra/storage/base.py`，定义 `Storage(ABC)`
- [ ] **改名 Adapter**：把 `src/infra/s3.py` 改成 `s3_adapter.py`，`class S3Adapter(Storage):`
- [ ] **新增 Factory 层**：建 `src/infra/storage/factory.py`
- [ ] **新增 Depends 层**：在 `src/app/dependencies.py` 加 `get_storage` 和 `get_file_service`
- [ ] **改 Service 层**：`FileService.__init__(db, storage: Storage)`，删所有 `get_s3_client` 直连
- [ ] **改 Route 层**：所有 `FileService.xxx(db, ...)` 改成 `service: FileService = Depends(get_file_service)`
- [ ] **lifespan 钩子**：用 `get_storage().ensure_bucket()` 替代 `get_s3_client().ensure_bucket()`
- [ ] **回归测试**：跑 3 类文件 × 4 类用户 = 12 个用例矩阵

---



## 附录 C：术语对照


| 术语                 | 含义                                      | 文档位置      |
| ------------------ | --------------------------------------- | --------- |
| **ABC**            | Abstract Base Class，抽象基类                | 第 2 章     |
| **Adapter**        | 继承 ABC 的具体类（S3Adapter、LocalAdapter）     | 第 3 章     |
| **Factory**        | 根据 env 返回不同 Adapter                     | 第 4 章     |
| **Depends**        | FastAPI 依赖注入，配合 `@lru_cache` 保单例        | 第 5 章     |
| `Storage(ABC)`     | 文件存储的统一接口契约（6 个 abstractmethod）         | 第 2.1 节   |
| `S3Adapter`        | S3/SeaweedFS 实现                         | 第 3.1 节   |
| `LocalAdapter`     | 本地文件系统实现（可选）                            | 第 3.4 节   |
| `StorageFactory`   | 读 `settings.storage_backend` 选 Adapter  | 第 4.3 节   |
| `get_storage`      | `Depends(get_storage)` 拿全局单例            | 第 5.1 节   |
| `get_file_service` | `Depends(get_file_service)` 拿业务 Service | 第 5.2 节   |
| **面向抽象编程**         | 业务只依赖 ABC，不依赖具体实现                       | 第 2.3 节   |
| **PROOF 鉴权**       | 通过 3 表 JOIN 反查文件所属申请人                   | 第 6.1.2 节 |
| **软删除**            | `is_deleted = True` + `delete_time` 标记  | 第 6.1.6 节 |


