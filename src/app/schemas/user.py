"""用户模块 DTO / VO

架构约定（与 file/template_category 一致）：
- Request 负责"接收输入 + 校验 + 提供转换方法（to_orm / apply_to）"
- VO      ：只做 ORM → 序列化投影，由 `from_orm_to_vo` 完成
- 列表场景使用 XXXListVO(Page[T]) 模式（service 用 Page.from_list_to_page 构造）

约定：
- UserResponse 是聚合所有字段的最大视图，按 endpoint 需求子集返回
- 各 VO 字段命名沿用前端 camelCase 约定
"""
from typing import Optional, List

from pydantic import BaseModel, Field, ConfigDict, field_validator

from src.app.schemas.page import Page


# ========== 请求 DTO ==========

class UpdateProfileRequest(BaseModel):
    """更新用户基本信息（avatar / phone）"""

    avatar: Optional[str] = Field(default=None, description="头像 URL")
    phone: Optional[str] = Field(default=None, max_length=15, description="手机号")

    def apply_to(self, user) -> bool:
        """把非空字段写回 ORM 对象。"""
        modified = False
        if self.avatar is not None:
            user.avatar = self.avatar
            modified = True
        if self.phone is not None:
            user.phone = self.phone
            modified = True
        return modified


class BindStudentRequest(BaseModel):
    """绑定学生信息"""

    fullName: str = Field(..., min_length=1, max_length=100)
    major: str = Field(..., min_length=1, max_length=100)
    grade: Optional[int] = Field(default=None, ge=1, le=5)
    graduationYear: Optional[int] = Field(default=None, ge=2000, le=2100)

    def apply_to(self, user) -> bool:
        """把请求字段写回 ORM 对象（业务校验：enrollment_year 由 graduationYear - 4 计算）。"""
        user.full_name = self.fullName
        user.major = self.major
        if self.grade is not None:
            user.grade = self.grade
        else:
            user.grade = 1
        if self.graduationYear is not None:
            user.enrollment_year = self.graduationYear - 4
        elif user.enrollment_year is None:
            user.enrollment_year = 2023
        return True


class UpdateStudentRequest(BaseModel):
    """更新学生信息（所有字段可选）"""

    fullName: Optional[str] = Field(default=None, min_length=1, max_length=100)
    major: Optional[str] = Field(default=None, min_length=1, max_length=100)
    grade: Optional[int] = Field(default=None, ge=1, le=5)
    graduationYear: Optional[int] = Field(default=None, ge=2000, le=2100)

    def apply_to(self, user) -> bool:
        """把非空字段写回 ORM 对象。"""
        modified = False
        if self.fullName is not None:
            user.full_name = self.fullName
            modified = True
        if self.major is not None:
            user.major = self.major
            modified = True
        if self.grade is not None:
            user.grade = self.grade
            modified = True
        if self.graduationYear is not None:
            user.enrollment_year = self.graduationYear - 4
            modified = True
        return modified


class UpdateUserStatusRequest(BaseModel):
    """管理员修改用户状态"""

    status: str = Field(..., description="active / inactive / banned")


class CreateUserRequest(BaseModel):
    """管理员创建用户"""

    username: str = Field(..., min_length=3, max_length=64)
    password: Optional[str] = Field(default=None, description="不传则自动生成 12 位随机密码")
    role: Optional[str] = Field(default="user", description="默认分配角色 code")


class BatchCreateUserRequest(BaseModel):
    """管理员批量创建用户"""

    usernames: List[str] = Field(..., min_length=1)


class UserQueryRequest(BaseModel):
    """管理员用户列表查询（GET /admin/list）"""

    model_config = ConfigDict(populate_by_name=True)

    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    username: Optional[str] = None
    fullName: Optional[str] = None


# ========== 响应 VO ==========

class UserProfileVO(BaseModel):
    """用户简要信息（GET /profile 等）"""

    userId: int
    username: str
    phone: Optional[str]
    avatar: Optional[str]
    roles: List[dict] = Field(default_factory=list, description="[{roleCode, roleName}]")
    status: str

    @classmethod
    def from_orm_to_vo(cls, obj, *, roles: Optional[List[dict]] = None) -> "UserProfileVO":
        return cls(
            userId=obj.id,
            username=obj.username,
            phone=obj.phone,
            avatar=obj.avatar,
            roles=roles or [],
            status=obj.status,
        )


class UserCompleteInfoVO(BaseModel):
    """用户完整信息（GET /complete-info，含学生 + 分数）"""

    userId: int
    username: str
    phone: Optional[str]
    avatar: Optional[str]
    email: str
    studentId: Optional[str]
    fullName: Optional[str]
    major: Optional[str]
    grade: Optional[int]
    graduationYear: Optional[int]
    enrollmentYear: Optional[int]
    gpa: Optional[float]
    academicScore: float
    specialtyScore: float
    comprehensiveScore: float
    isConfirmed: bool
    demandValue: Optional[dict]
    demandFiles: Optional[dict]

    @classmethod
    def from_orm_to_vo(cls, obj) -> "UserCompleteInfoVO":
        return cls(
            userId=obj.id,
            username=obj.username,
            phone=obj.phone,
            avatar=obj.avatar,
            email=obj.username,
            studentId=obj.student_id,
            fullName=obj.full_name,
            major=obj.major,
            grade=obj.grade,
            graduationYear=obj.graduation_year,
            enrollmentYear=obj.enrollment_year,
            gpa=obj.gpa,
            academicScore=obj.academic_score or 0.0,
            specialtyScore=obj.specialty_score or 0.0,
            comprehensiveScore=obj.comprehensive_score or 0.0,
            isConfirmed=obj.is_confirmed,
            demandValue=obj.demand_value,
            demandFiles=obj.demand_files,
        )


class UserStudentInfoVO(BaseModel):
    """学生信息子集（GET /student/info）"""

    studentId: Optional[str]
    enrollmentYear: Optional[int]
    fullName: Optional[str]
    major: Optional[str]
    grade: Optional[int]
    graduationYear: Optional[int]
    gpa: Optional[float]
    academicScore: float
    specialtyScore: float
    comprehensiveScore: float
    isConfirmed: bool
    demandValue: Optional[dict]
    demandFiles: Optional[dict]

    @classmethod
    def from_orm_to_vo(cls, obj) -> "UserStudentInfoVO":
        return cls(
            studentId=obj.student_id,
            enrollmentYear=obj.enrollment_year,
            fullName=obj.full_name,
            major=obj.major,
            grade=obj.grade,
            graduationYear=obj.graduation_year,
            gpa=obj.gpa,
            academicScore=obj.academic_score or 0.0,
            specialtyScore=obj.specialty_score or 0.0,
            comprehensiveScore=obj.comprehensive_score or 0.0,
            isConfirmed=obj.is_confirmed,
            demandValue=obj.demand_value,
            demandFiles=obj.demand_files,
        )


class UserAdminListItemVO(BaseModel):
    """管理员用户列表条目（GET /admin/list）"""

    userId: int
    username: str
    phone: Optional[str]
    roles: List[str] = Field(default_factory=list)
    status: str
    lastLoginAt: Optional[str]
    fullName: Optional[str]
    major: Optional[str]
    grade: Optional[int]
    graduationYear: Optional[int]

    @classmethod
    def from_orm_to_vo(cls, obj, *, roles: Optional[List[str]] = None) -> "UserAdminListItemVO":
        return cls(
            userId=obj.id,
            username=obj.username,
            phone=obj.phone,
            roles=roles or [],
            status=obj.status,
            lastLoginAt=obj.last_login_at,
            fullName=obj.full_name,
            major=obj.major,
            grade=obj.grade,
            graduationYear=obj.graduation_year,
        )


class UserAdminListVO(Page[UserAdminListItemVO]):
    """管理员用户分页列表 VO"""

    pass


class UserScoreVO(BaseModel):
    """用户积分视图"""

    academic: float
    specialty: float
    comprehensive: float
    total: float

    @classmethod
    def from_orm_to_vo(cls, obj) -> "UserScoreVO":
        a = obj.academic_score or 0.0
        s = obj.specialty_score or 0.0
        c = obj.comprehensive_score or 0.0
        return cls(academic=a, specialty=s, comprehensive=c, total=a + s + c)


class CurrentUserInfoVO(BaseModel):
    """当前登录用户（GET /me）"""

    userId: int
    username: str
    fullName: Optional[str]
    avatar: Optional[str]
    roles: List[dict] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)

    @classmethod
    def from_orm_to_vo(
        cls,
        obj,
        *,
        roles: Optional[List[dict]] = None,
        permissions: Optional[List[str]] = None,
    ) -> "CurrentUserInfoVO":
        return cls(
            userId=obj.id,
            username=obj.username,
            fullName=obj.full_name,
            avatar=obj.avatar,
            roles=roles or [],
            permissions=permissions or [],
        )


__all__ = [
    "UpdateProfileRequest",
    "BindStudentRequest",
    "UpdateStudentRequest",
    "UpdateUserStatusRequest",
    "CreateUserRequest",
    "BatchCreateUserRequest",
    "UserQueryRequest",
    "UserProfileVO",
    "UserCompleteInfoVO",
    "UserStudentInfoVO",
    "UserAdminListItemVO",
    "UserAdminListVO",
    "UserScoreVO",
    "CurrentUserInfoVO",
]
