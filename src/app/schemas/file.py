"""文件模块 DTO / VO / 内部工具

架构约定（见 docs/file/分层设计.md）：
- Request 负责"接收输入 + 校验 + 提供转换方法（to_metadata / apply_to / to_conditions）"
- VO 只做"ORM → 序列化"的投影，不含 url 等访问字段
- VO 不含 url，url 走 FileDataVO（预览/下载场景独立接口）
- 工具函数（_build_object_name / _format_size）放在本模块，以便 Request 复用
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Generic, TypeVar

from fastapi import UploadFile
from pydantic import BaseModel, Field, ConfigDict, field_validator
from sqlalchemy import and_

from src.models import FileCategory, FileMetadata


# ========== 内部工具（service 层会复用） ==========

def _build_object_name(category: str, original_name: str, user_id: int) -> str:
    """生成 S3 对象 key

    格式：{category}/{year}/{user_id}/{uuid}.{ext}
    """
    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if ext and len(ext) > 10:
        ext = ext[:10]
    unique_id = uuid.uuid4().hex
    year = datetime.utcnow().year
    category_prefix = category.lower()
    if ext:
        return f"{category_prefix}/{year}/{user_id}/{unique_id}.{ext}"
    return f"{category_prefix}/{year}/{user_id}/{unique_id}"


def _format_size(size: Optional[int]) -> str:
    """人类友好的文件大小"""
    if size is None:
        return "-"
    if size < 1024:
        return f"{size}B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f}KB"
    return f"{size / (1024 * 1024):.1f}MB"


# ========== 通用分页容器（跨模块复用，文件模块也用） ==========

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """通用分页响应容器"""
    list: List[T]
    total: int
    pageNum: int
    pageSize: int
    pages: int

    @classmethod
    def build(
        cls,
        items: List[T],
        total: int,
        page_num: int,
        page_size: int,
    ) -> "Page[T]":
        pages = (total + page_size - 1) // page_size if total > 0 else 0
        return cls(
            list=items,
            total=total,
            pageNum=page_num,
            pageSize=page_size,
            pages=pages,
        )


# ========== 请求 DTO ==========

class FileUploadRequest(BaseModel):
    """文件上传请求——DTO 承担数据校验与 ORM 构造"""
    fileCategory: str = Field(default="PROOF", description="文件分类")
    file: UploadFile = Field(...)
    content: bytes = Field(...)

    @field_validator("fileCategory")
    @classmethod
    def normalize_category(cls, v: str) -> str:
        return v.upper() if v else "PROOF"

    def to_metadata(self, user_id: int) -> FileMetadata:
        """根据本请求构造 ORM 对象（service 层只负责落库，不重复计算 key/ext）"""
        original_name = self.file.filename or "unnamed"
        ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
        if ext and len(ext) > 10:
            ext = ext[:10]
        content_type = self.file.content_type or "application/octet-stream"
        object_name = _build_object_name(self.fileCategory, original_name, user_id)
        return FileMetadata(
            object_name=object_name,
            original_name=original_name,
            file_size=len(self.content),
            content_type=content_type,
            file_extension=ext,
            file_category=FileCategory(self.fileCategory),
            upload_user_id=user_id,
        )


class FileAvatarUploadRequest(BaseModel):
    """头像上传请求——DTO 构造 ORM（含命名/ext/分类固定逻辑）"""
    content: bytes = Field(...)
    contentType: str = Field(default="image/jpeg", description="头像 MIME 类型")

    @field_validator("contentType")
    @classmethod
    def normalize_content_type(cls, v: str) -> str:
        return v or "image/jpeg"

    def to_metadata(self, user_id: int) -> FileMetadata:
        """构造头像 ORM 对象：固定命名 avatar_{user_id}.jpg、AVATAR 分类"""
        original_name = f"avatar_{user_id}.jpg"
        object_name = _build_object_name(
            FileCategory.AVATAR.value, original_name, user_id
        )
        return FileMetadata(
            object_name=object_name,
            original_name=original_name,
            file_size=len(self.content),
            content_type=self.contentType,
            file_extension="jpg",
            file_category=FileCategory.AVATAR,
            upload_user_id=user_id,
        )


class FileUpdateRequest(BaseModel):
    """文件元信息更新请求——目前仅支持重命名

    DTO 承担"非空字段写回 ORM"职责，service 不再判断字段是否非空。
    """
    originalName: Optional[str] = Field(default=None, description="新文件名")

    def apply_to(self, meta: FileMetadata) -> bool:
        """把非空字段写回 ORM 对象。返回是否有字段被实际修改。

        返回值约定：False 表示"没有任何字段被修改"，service 应跳过 commit。
        """
        modified = False
        if self.originalName is not None:
            meta.original_name = self.originalName
            modified = True
        return modified


class FileQueryRequest(BaseModel):
    """文件查询请求——DTO 承担"字段→ORM where 条件"翻译职责

    配置 `populate_by_name=True`：既支持驼峰字段名（`fileName`）也支持下划线
    （`file_name`）传入，便于 FastAPI Query 自动解析（参见 §5.3）。
    """
    model_config = ConfigDict(populate_by_name=True)

    fileName: Optional[str] = Field(default=None, description="文件名模糊查询")
    fileCategory: Optional[str] = Field(default=None, description="文件分类")
    uploadUserId: Optional[int] = Field(default=None, description="上传用户 ID")
    startTime: Optional[str] = Field(default=None, description="开始时间（ISO8601）")
    endTime: Optional[str] = Field(default=None, description="结束时间（ISO8601）")
    pageNum: int = Field(default=1, ge=1, description="页码")
    pageSize: int = Field(default=20, ge=1, le=100, description="每页大小")

    def _parse_iso(self, s: Optional[str]) -> Optional[datetime]:
        """容错解析 ISO8601 字符串

        支持以下输入：
          - '2026-07-04T10:30:00'         (前端 el-date-picker value-format 默认)
          - '2026-07-04T10:30:00Z'        (UTC)
          - '2026-07-04T10:30:00+08:00'   (带时区)
          - '2026-07-04 10:30:00'         (空格分隔，el-date-picker format 常见)
          - '2026-07-04'                  (仅日期)

        解析失败返回 None（让 service 跳过该条件，而非抛 500）。
        """
        if not s:
            return None
        s = s.strip().replace(" ", "T")
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            # 容错：去掉秒数（'2026-07-04T10:30'）
            try:
                dt = datetime.fromisoformat(s.rsplit(":", 1)[0])
            except ValueError:
                return None
        # 统一转 UTC-naive（与 created_at 字段 DateTime UTC-naive 对齐）
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt

    def to_conditions(self) -> list:
        """翻译为本请求对应的 SQLAlchemy where 条件列表

        返回值：每项是一个 SQLAlchemy 表达式（column.op.value），service 直接
        `select(...).where(*conditions)` 即可。
        """
        conds: list = []
        if self.fileName:
            conds.append(FileMetadata.original_name.ilike(f"%{self.fileName}%"))
        if self.fileCategory:
            try:
                conds.append(
                    FileMetadata.file_category == FileCategory(self.fileCategory.upper())
                )
            except ValueError:
                # 接受任何大小写 / 别名，服务层归一化失败时不再抛异常
                conds.append(FileMetadata.file_category == self.fileCategory)
        if self.uploadUserId is not None:
            conds.append(FileMetadata.upload_user_id == self.uploadUserId)
        if (start := self._parse_iso(self.startTime)) is not None:
            conds.append(FileMetadata.created_at >= start)
        if (end := self._parse_iso(self.endTime)) is not None:
            conds.append(FileMetadata.created_at <= end)
        return conds


# ========== 响应 VO ==========

class FileVO(BaseModel):
    """文件元信息视图——仅包含文件本身的客观属性，供前端列表/详情展示

    注意：不包含 url，url 走 FileDataVO 单独接口。
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    originalName: str
    fileSize: int
    fileSizeFormatted: str
    contentType: Optional[str]
    fileExtension: Optional[str]
    fileCategory: str
    uploadUserId: int
    uploadTime: str

    @classmethod
    def normalize_extension(cls, v: Optional[str]) -> Optional[str]:
        """统一扩展名字段为带点格式（如 '.pptx'），与前端约定一致"""
        if not v:
            return v
        v = v.strip().lower()
        if not v:
            return None
        return v if v.startswith(".") else f".{v}"

    @classmethod
    def from_orm_obj(cls, obj) -> "FileVO":
        cat = obj.file_category.value if hasattr(obj.file_category, "value") else obj.file_category
        return cls(
            id=obj.id,
            originalName=obj.original_name,
            fileSize=obj.file_size,
            fileSizeFormatted=_format_size(obj.file_size),
            contentType=obj.content_type,
            fileExtension=cls.normalize_extension(obj.file_extension),
            fileCategory=cat,
            uploadUserId=obj.upload_user_id,
            uploadTime=obj.created_at.isoformat(timespec="milliseconds") if obj.created_at else None,
        )


class FileListVO(Page[FileVO]):
    """文件分页查询结果——即 Page[FileVO]，作为模块级语义别名"""
    pass


class FileDataVO(BaseModel):
    """文件数据视图——仅包含预览/下载所需的最小字段

    与 FileVO 的差异：少了无意义的元信息（大小、时间等），多了 url。
    预览接口必须返回此 VO 四字段（id / originalName / contentType / url）。
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    originalName: str
    contentType: Optional[str]
    url: str

    @classmethod
    def from_orm_obj(cls, obj, url: str) -> "FileDataVO":
        return cls(
            id=obj.id,
            originalName=obj.original_name,
            contentType=obj.content_type,
            url=url,
        )


__all__ = [
    "_build_object_name",
    "_format_size",
    "Page",
    "FileUploadRequest",
    "FileAvatarUploadRequest",
    "FileUpdateRequest",
    "FileQueryRequest",
    "FileVO",
    "FileListVO",
    "FileDataVO",
]