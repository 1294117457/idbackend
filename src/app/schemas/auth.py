"""认证模块 DTO / VO

架构约定（与 file/template_category 一致）：
- Request 负责"接收输入 + 校验"
- VO      ：只做"返回值序列化"

约定：
- 登录 / 注册的 Request 直接喂给 AuthService —— service 不再展开字段
- token 对直接用 VO 表示
"""
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ========== 请求 DTO ==========

class LoginRequest(BaseModel):
    """登录请求（含图形验证码）"""

    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=1)
    verifyCode: Optional[str] = Field(default=None, description="图形验证码文字")
    captchaId: Optional[str] = Field(default=None, description="图形验证码 ID")


class RegisterRequest(BaseModel):
    """注册请求（需邮箱验证码）"""

    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6)
    code: str = Field(..., description="邮箱验证码")

    def to_create_orm(self) -> "User":
        """根据本请求构造一个新的 ORM 用户对象（service 直接落库前一行调用即可）。

        构造的字段：
        - username / password (hash 后) / status="active"

        用户名冲突校验、UserRole 关联交给 service 处理。
        """
        from src.models.user import User
        from src.infra.jwt import hash_password

        return User(
            username=self.username,
            password=hash_password(self.password),
            status="active",
        )


class SendCodeRequest(BaseModel):
    """发送验证码请求"""

    email: str = Field(...)
    type: str = Field(default="register", description="register / reset")
    captchaId: Optional[str] = Field(default=None, description="图形验证码 ID")
    captchaCode: Optional[str] = Field(default=None, description="图形验证码答案")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        if "@" not in v:
            raise ValueError("Invalid email format")
        return v


class RefreshTokenRequest(BaseModel):
    """刷新 token 请求"""

    refreshToken: str = Field(..., min_length=1)


class LogoutRequest(BaseModel):
    """登出请求（撤销 refresh token）"""

    refreshToken: str = Field(..., min_length=1)


class ForgotPasswordRequest(BaseModel):
    """重置密码请求"""

    username: str = Field(..., min_length=3, max_length=64)
    code: str = Field(..., description="邮箱验证码")
    newPassword: str = Field(..., min_length=6)
    confirmPassword: str = Field(..., min_length=6)

    @field_validator("confirmPassword")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if "newPassword" in info.data and v != info.data["newPassword"]:
            raise ValueError("两次密码不一致")
        return v

    def apply_to(self, user) -> bool:
        """把请求中的 newPassword 写回 user ORM（hash 后）。返回 True 表示已修改。"""
        from src.infra.jwt import hash_password

        user.password = hash_password(self.newPassword)
        return True


# ========== 响应 VO ==========

class AuthTokenPairVO(BaseModel):
    """token 对（access + refresh + 过期）"""

    accessToken: str
    refreshToken: str
    expiresIn: int = Field(default=86400, description="秒")


class UserCreateResultVO(BaseModel):
    """创建用户成功返回值（/register、/admin/create 用）"""

    userId: int
    username: str


class CaptchaVO(BaseModel):
    """图形验证码返回值"""

    captchaId: str
    base64: str


__all__ = [
    "LoginRequest",
    "RegisterRequest",
    "SendCodeRequest",
    "RefreshTokenRequest",
    "LogoutRequest",
    "ForgotPasswordRequest",
    "AuthTokenPairVO",
    "UserCreateResultVO",
    "CaptchaVO",
]
