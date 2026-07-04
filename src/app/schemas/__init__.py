"""Pydantic 模型 - 请求/响应 DTO"""
from pydantic import BaseModel, field_validator
from typing import Optional, List
from datetime import datetime


# ========== 认证相关 ==========

class LoginRequest(BaseModel):
    username: str
    password: str
    verifyCode: Optional[str] = None
    captchaId: Optional[str] = None


class RegisterRequest(BaseModel):
    username: str
    password: str
    code: str


class SendCodeRequest(BaseModel):
    email: str
    type: str = "register"

    @field_validator('email')
    @classmethod
    def validate_email(cls, v):
        if '@' not in v:
            raise ValueError('Invalid email format')
        return v


class ResetPasswordRequest(BaseModel):
    email: str
    code: str
    newPassword: str
    confirmPassword: str

    @field_validator('email')
    @classmethod
    def validate_email(cls, v):
        if '@' not in v:
            raise ValueError('Invalid email format')
        return v


class LoginResponse(BaseModel):
    accessToken: str
    refreshToken: str
    expiresIn: int


# ========== 用户相关 ==========

class BindStudentRequest(BaseModel):
    fullName: str
    major: str
    grade: Optional[int] = None
    graduationYear: Optional[int] = None


class UpdateProfileRequest(BaseModel):
    phone: Optional[str] = None
    avatar: Optional[str] = None


class UserResponse(BaseModel):
    userId: int
    username: str
    phone: Optional[str]
    avatar: Optional[str]
    status: str
    role: str
    fullName: Optional[str]
    studentId: Optional[str]
    major: Optional[str]
    grade: Optional[int]
    isConfirmed: bool
    academicScore: float
    specialtyScore: float
    comprehensiveScore: float

    class Config:
        from_attributes = True


class UserScoreResponse(BaseModel):
    academic: float
    specialty: float
    comprehensive: float
    total: float


# ========== 申请相关 ==========

class ProofItem(BaseModel):
    proofFileId: int
    proofValue: float
    reviewCount: Optional[int] = 1
    remark: Optional[str] = None


class SubmitApplicationRequest(BaseModel):
    studentId: str
    studentName: str
    major: str
    enrollmentYear: int
    templateName: str
    templateType: str
    scoreType: int
    applyScore: float
    applyInput: Optional[float] = None
    ruleId: Optional[int] = None
    reviewCount: int = 1
    proofItems: List[ProofItem] = []
    remark: Optional[str] = None


class ApplicationResponse(BaseModel):
    id: int
    studentName: str
    templateName: str
    applyScore: float
    gainScore: Optional[float]
    status: int
    createdAt: datetime

    class Config:
        from_attributes = True


class ReviewRequest(BaseModel):
    comment: Optional[str] = None


# ========== 模板相关 ==========

class TemplateResponse(BaseModel):
    id: int
    templateName: str
    templateType: str
    scoreType: int
    maxScore: float
    inputUnit: str
    description: Optional[str]

    class Config:
        from_attributes = True


class CreateTemplateRequest(BaseModel):
    templateName: str
    templateType: str = "CONDITION"
    maxScore: float
    scoreType: int = 0
    inputUnit: str = ""
    description: str = ""
    reviewCount: int = 1


# ========== 文件相关 ==========

class UploadResponse(BaseModel):
    """通用文件上传响应"""
    fileId: int
    url: str
    originalName: str


class FileUpdateRequest(BaseModel):
    """文件元信息更新请求"""
    originalName: Optional[str] = None
    filePurpose: Optional[str] = None


def _format_size(size: Optional[int]) -> str:
    """人类友好的文件大小（业务层格式化）"""
    if size is None:
        return "-"
    if size < 1024:
        return f"{size}B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f}KB"
    return f"{size / (1024 * 1024):.1f}MB"


class FileMetadataVO(BaseModel):
    """文件元信息视图（用于 list / info）"""
    id: int
    originalName: str
    fileSize: int
    fileSizeFormatted: str
    contentType: Optional[str]
    fileExtension: Optional[str]
    fileCategory: str
    filePurpose: Optional[str] = None
    uploadUserId: int
    uploadTime: str

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_obj(cls, obj) -> "FileMetadataVO":
        """从 FileMetadata ORM 对象构造"""
        return cls(
            id=obj.id,
            originalName=obj.original_name,
            fileSize=obj.file_size,
            fileSizeFormatted=_format_size(obj.file_size),
            contentType=obj.content_type,
            fileExtension=obj.file_extension,
            fileCategory=obj.file_category.value if hasattr(obj.file_category, "value") else obj.file_category,
            filePurpose=obj.file_purpose,
            uploadUserId=obj.upload_user_id,
            uploadTime=str(obj.created_at),
        )


class FileInfoVO(BaseModel):
    """单个文件简要信息（GET /api/file/{id}）"""
    fileId: int
    originalName: str
    fileSize: int
    contentType: Optional[str]
    fileCategory: str
    uploadTime: str

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_obj(cls, obj) -> "FileInfoVO":
        return cls(
            fileId=obj.id,
            originalName=obj.original_name,
            fileSize=obj.file_size,
            contentType=obj.content_type,
            fileCategory=obj.file_category.value if hasattr(obj.file_category, "value") else obj.file_category,
            uploadTime=str(obj.created_at),
        )


class FileUpdateResponse(BaseModel):
    """文件元信息更新响应"""
    fileId: int
    originalName: str
    filePurpose: Optional[str]
    fileCategory: str

    @classmethod
    def from_orm_obj(cls, obj) -> "FileUpdateResponse":
        return cls(
            fileId=obj.id,
            originalName=obj.original_name,
            filePurpose=obj.file_purpose,
            fileCategory=obj.file_category.value if hasattr(obj.file_category, "value") else obj.file_category,
        )


# ========== 分页 ==========

class PaginatedResponse(BaseModel):
    list: List
    total: int
    page: int
    size: int
