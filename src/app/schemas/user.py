"""用户模块 DTO / VO

架构约定：
- Request 负责"接收输入 + 校验"
- VO 只做 ORM → 序列化投影，由 `from_orm_to_vo` 完成
- 列表场景使用 XXXListVO(Page[T]) 模式
"""
from typing import Optional, List

from pydantic import BaseModel, Field, ConfigDict

from src.app.schemas.page import Page


# ========== 请求 DTO ==========

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
    """管理员用户列表查询"""
    model_config = ConfigDict(populate_by_name=True)
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    username: Optional[str] = None
    fullName: Optional[str] = None


class UpdateUserMeRequest(BaseModel):
    """更新用户账户信息（PUT /api/users/me）"""
    phone: Optional[str] = Field(default=None, max_length=15)
    full_name: Optional[str] = Field(default=None, max_length=100)
    avatar: Optional[str] = Field(default=None, max_length=500)
    grade: Optional[int] = Field(default=None, ge=1, le=10)
    enrollment_year: Optional[int] = Field(default=None, ge=2000, le=2100)
    graduation_year: Optional[int] = Field(default=None, ge=2000, le=2100)
    major: Optional[str] = Field(default=None, max_length=100)


# ========== 响应 VO ==========

class CurrentUserInfoVO(BaseModel):
    """当前登录用户（GET /api/system/user/me）"""
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


class UserAdminListItemVO(BaseModel):
    """管理员用户列表条目"""
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
    studentId: Optional[str]

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
            studentId=obj.extract_student_id(obj.username),
        )


class UserAdminListVO(Page[UserAdminListItemVO]):
    """管理员用户分页列表 VO"""
    pass


__all__ = [
    "UpdateUserStatusRequest",
    "CreateUserRequest",
    "BatchCreateUserRequest",
    "UserQueryRequest",
    "UpdateUserMeRequest",
    "CurrentUserInfoVO",
    "UserAdminListItemVO",
    "UserAdminListVO",
]
