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
    fileId: int
    url: str
    originalName: str


# ========== 分页 ==========

class PaginatedResponse(BaseModel):
    list: List
    total: int
    page: int
    size: int
