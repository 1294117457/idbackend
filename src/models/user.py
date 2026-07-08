"""用户、角色、权限模型"""
from sqlalchemy import String, Enum, Boolean, Integer, ForeignKey, Table, Column, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List
import enum

from .base import Base, TimestampMixin


class UserStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    BANNED = "banned"


class UserRole(Base, TimestampMixin):
    """用户角色关联表"""
    __tablename__ = "user_role"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role_id: Mapped[int] = mapped_column(ForeignKey("role.id", ondelete="CASCADE"))


class RolePermission(Base, TimestampMixin):
    """角色权限关联表"""
    __tablename__ = "role_permission"

    role_id: Mapped[int] = mapped_column(ForeignKey("role.id", ondelete="CASCADE"))
    permission_id: Mapped[int] = mapped_column(
        ForeignKey("permission.id", ondelete="CASCADE")
    )


class Role(Base, TimestampMixin):
    """角色表"""
    __tablename__ = "role"

    role_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    role_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[bool] = mapped_column(Boolean, default=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)

    # 关系
    users: Mapped[List["User"]] = relationship(
        "User", secondary="user_role", back_populates="roles"
    )
    permissions: Mapped[List["Permission"]] = relationship(
        "Permission", secondary="role_permission", back_populates="roles"
    )


class Permission(Base, TimestampMixin):
    """权限表"""
    __tablename__ = "permission"

    permission_code: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, doc="权限编码，如 user:read"
    )
    permission_name: Mapped[str] = mapped_column(
        String(100), nullable=False, doc="权限名称"
    )
    api_path: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, doc="对应后端接口路径"
    )
    description: Mapped[Optional[str]] = mapped_column(String(255))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[bool] = mapped_column(Boolean, default=True)

    @property
    def code(self) -> str:
        return self.permission_code

    @property
    def name(self) -> str:
        return self.permission_name

    @property
    def route_path(self) -> Optional[str]:
        return self.api_path

    # 关系
    roles: Mapped[List["Role"]] = relationship(
        "Role", secondary="role_permission", back_populates="permissions"
    )


class User(Base, TimestampMixin):
    """用户表"""
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(15))
    avatar: Mapped[Optional[str]] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default=UserStatus.ACTIVE.value)
    last_login_at: Mapped[Optional[str]] = mapped_column(String(50))

    # 学生信息
    full_name: Mapped[Optional[str]] = mapped_column(String(100))
    grade: Mapped[Optional[int]] = mapped_column(Integer)
    graduation_year: Mapped[Optional[int]] = mapped_column(Integer)
    enrollment_year: Mapped[Optional[int]] = mapped_column(Integer)
    major: Mapped[Optional[str]] = mapped_column(String(100))

    # 成绩快照（由 recalculate 写入）
    score_info: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)

    # 备用扩展槽（学生维度动态扩展）
    extra_info: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)

    # 关系
    roles: Mapped[List["Role"]] = relationship(
        "Role", secondary="user_role", back_populates="users"
    )
    applications: Mapped[List["Application"]] = relationship(back_populates="user")

    @property
    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE.value

    @staticmethod
    def extract_student_id(username: str) -> Optional[str]:
        """从 username 提取学号

        规则: username 格式为 "学号@stu.xmu.edu.cn"
        例如: "33120202201909@stu.xmu.edu.cn" -> "33120202201909"
        """
        if '@' in username:
            prefix = username.split('@')[0]
            if prefix.isdigit():
                return prefix
        return None
