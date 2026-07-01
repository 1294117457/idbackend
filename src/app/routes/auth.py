"""认证路由 - 兼容前端"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional

from src.app.deps import get_db, get_current_user, CurrentUser, ip_rate_limit
from src.app.response import success_response, error_response
from src.services import AuthService, UserService
from src.infra.jwt import JWTError
from src.infra.captcha import Captcha
from src.infra.email import EmailCode


router = APIRouter(prefix="/api/authserver", tags=["认证"])


# ========== 请求/响应模型 ==========


class LoginRequest(BaseModel):
    username: str
    password: str
    verifyCode: Optional[str] = None
    captchaId: Optional[str] = None


class RegisterRequest(BaseModel):
    username: str
    password: str
    code: str  # 邮箱验证码


class SendCodeRequest(BaseModel):
    email: str
    type: str = "register"


class RefreshTokenRequest(BaseModel):
    refreshToken: str


class LogoutRequest(BaseModel):
    refreshToken: str


class ForgotPasswordRequest(BaseModel):
    username: str
    code: str
    newPassword: str
    confirmPassword: str


# ========== 认证接口 ==========


@router.post("/login")
async def login(
    request: LoginRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(ip_rate_limit("login", max_count=10, window_seconds=60)),
):
    """用户登录"""
    # 图形验证码校验
    if not request.captchaId or not request.verifyCode:
        return error_response("请完成图形验证码", code=400)
    is_valid, err = await Captcha.verify(request.captchaId, request.verifyCode)
    if not is_valid:
        return error_response(err, code=400)

    try:
        user, access_token, refresh_token = await AuthService.login(
            db, request.username, request.password
        )
        return success_response(
            {
                "accessToken": access_token,
                "refreshToken": refresh_token,
                "expiresIn": 86400,
            }
        )
    except ValueError as e:
        return error_response(str(e), code=401)


@router.post("/register")
async def register(
    request: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """用户注册"""
    try:
        # 前置校验：邮箱验证码
        ok, err = await EmailCode.verify(request.username, "register", request.code)
        if not ok:
            return error_response(err, code=400)

        user = await AuthService.register(db, request.username, request.password)
        return success_response(
            {
                "userId": user.id,
                "username": user.username,
            }
        )
    except ValueError as e:
        return error_response(str(e), code=400)


@router.post("/refresh")
async def refresh_token(
    request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    """刷新Token"""
    try:
        new_access, new_refresh = await AuthService.refresh(
            db, request.refreshToken
        )
        return success_response(
            {
                "accessToken": new_access,
                "refreshToken": new_refresh,
                "expiresIn": 86400,
            }
        )
    except JWTError as e:
        return error_response(str(e), code=401)
    except Exception as e:
        return error_response(str(e), code=401)


@router.post("/logout")
async def logout(
    request: LogoutRequest,
    user: CurrentUser = Depends(get_current_user),
):
    """登出，撤销 refresh token"""
    await AuthService.revoke_refresh_token(request.refreshToken)
    return success_response(msg="已登出")


@router.post("/sendEmailCode")
async def send_email_code(
    request: SendCodeRequest,
    _: None = Depends(ip_rate_limit("send_email_code", max_count=5, window_seconds=60)),
):
    """发送邮箱验证码（注册用）"""
    ok, err = await EmailCode.send(request.email, request.type)
    if not ok:
        return error_response(err, code=429)
    return success_response(msg="验证码已发送")


@router.post("/sendResetCode")
async def send_reset_code(
    request: SendCodeRequest,
    _: None = Depends(ip_rate_limit("send_reset_code", max_count=5, window_seconds=60)),
):
    """发送重置密码验证码"""
    ok, err = await EmailCode.send(request.email, "reset")
    if not ok:
        return error_response(err, code=429)
    return success_response(msg="验证码已发送")


@router.post("/reset-password")
async def reset_password(
    request: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """重置密码"""
    try:
        # 前置校验：重置密码验证码
        ok, err = await EmailCode.verify(request.username, "reset", request.code)
        if not ok:
            return error_response(err, code=400)

        if request.newPassword != request.confirmPassword:
            return error_response("两次密码不一致", code=400)

        await AuthService.reset_password(db, request.username, request.newPassword)
        return success_response(msg="密码重置成功")
    except ValueError as e:
        return error_response(str(e), code=400)


# ========== 图形验证码 ==========


@router.get("/captcha/generate")
async def get_captcha(
    _: None = Depends(ip_rate_limit("captcha", max_count=20, window_seconds=60)),
):
    """获取图形验证码"""
    captcha_id, base64_image = await Captcha.generate()
    return success_response(
        {
            "captchaId": captcha_id,
            "base64": f"data:image/png;base64,{base64_image}",
        }
    )


# ========== 当前用户 ==========


@router.get("/me")
async def get_current_user_info(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户信息"""
    db_user = await UserService.get_user_by_id(db, user.user_id)
    if not db_user:
        return error_response("用户不存在", code=404)

    return success_response(
        {
            "userId": db_user.id,
            "username": db_user.username,
            "role": db_user.role,
            "fullName": db_user.full_name,
            "studentId": db_user.student_id,
            "isConfirmed": db_user.is_confirmed,
        }
    )
