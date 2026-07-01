"""认证路由 - 兼容前端"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional

from src.app.deps import get_db, get_current_user, CurrentUser
from src.app.response import success_response, error_response
from src.services import AuthService, UserService
from src.services.captcha_service import CaptchaService

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
):
    """用户登录"""
    try:
        user, token = await AuthService.login(
            db, request.username, request.password
        )
        # 前端期望的响应格式
        return success_response({
            "accessToken": token,
            "refreshToken": token,  # TODO: 生成独立的 refresh token
            "expiresIn": 86400,  # 24小时
        })
    except ValueError as e:
        return error_response(str(e), code=401)


@router.post("/register")
async def register(
    request: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """用户注册"""
    try:
        # 验证邮箱验证码
        is_valid = await AuthService.verify_code(request.username, "register", request.code)
        if not is_valid:
            return error_response("验证码错误", code=400)

        user = await AuthService.register(
            db, request.username, request.password
        )
        return success_response({
            "userId": user.id,
            "username": user.username,
        })
    except ValueError as e:
        return error_response(str(e), code=400)


@router.post("/refresh")
async def refresh_token(
    request: RefreshTokenRequest,
):
    """刷新Token"""
    try:
        # TODO: 实现真正的 refresh token 机制
        payload = await AuthService.verify_refresh_token(request.refreshToken)
        new_token = await AuthService.create_token(
            user_id=payload.get("userId"),
            username=payload.get("username"),
            role=payload.get("role"),
        )
        return success_response({
            "accessToken": new_token,
            "refreshToken": new_token,
            "expiresIn": 86400,
        })
    except Exception as e:
        return error_response(str(e), code=401)


@router.post("/sendEmailCode")
async def send_email_code(
    request: SendCodeRequest,
):
    """发送邮箱验证码"""
    try:
        await AuthService.send_verification_code(
            request.email, request.type
        )
        return success_response(msg="验证码已发送")
    except Exception as e:
        return error_response(str(e), code=500)


@router.post("/sendResetCode")
async def send_reset_code(
    request: SendCodeRequest,
):
    """发送重置密码验证码"""
    try:
        await AuthService.send_verification_code(
            request.email, "reset"
        )
        return success_response(msg="验证码已发送")
    except Exception as e:
        return error_response(str(e), code=500)


@router.post("/reset-password")
async def reset_password(
    request: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """重置密码"""
    try:
        # 验证验证码
        is_valid = await AuthService.verify_code(request.username, "reset", request.code)
        if not is_valid:
            return error_response("验证码错误", code=400)

        if request.newPassword != request.confirmPassword:
            return error_response("两次密码不一致", code=400)

        await AuthService.reset_password(db, request.username, request.newPassword)
        return success_response(msg="密码重置成功")
    except ValueError as e:
        return error_response(str(e), code=400)


# ========== 图形验证码 ==========

@router.get("/captcha/generate")
async def get_captcha():
    """获取图形验证码"""
    captcha_id, base64_image = await CaptchaService.generate_captcha()
    return success_response({
        "captchaId": captcha_id,
        "base64": f"data:image/png;base64,{base64_image}",
    })


@router.post("/captcha/verify")
async def verify_captcha(
    captchaId: str,
    code: str,
):
    """验证图形验证码"""
    is_valid, error_msg = await CaptchaService.validate_captcha(captchaId, code)
    if not is_valid:
        return error_response(error_msg, code=400)
    return success_response(msg="验证成功")


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

    return success_response({
        "userId": db_user.id,
        "username": db_user.username,
        "role": db_user.role,
        "fullName": db_user.full_name,
        "studentId": db_user.student_id,
        "isConfirmed": db_user.is_confirmed,
    })
