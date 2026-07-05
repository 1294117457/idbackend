"""认证路由 - 兼容前端

架构约定：
- Request 直接喂给 service（service 内部接 username/password 等简单参数）
- 业务异常 → 由全局 exception_handlers 自动翻译为 HTTP 响应（BadRequestError / UnauthorizedError / ConflictError）
- VO 由 schema 生成

注意：
- 登录/刷新：BadRequestError 走到 handler 后是 400。前端旧逻辑期望 401，但 exception_handlers
  会按 BusinessError.http_code 返回——BadRequestError=400。考虑到鉴权主要靠中间件，
  登录失败用 400 是合理的（前端通过 errorCode=BAD_REQUEST 判断）。
- 注册：ConflictError（用户名已存在）由 handler 自动 409。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.deps import get_db, ip_rate_limit
from src.app.context import get_user_id, get_user_roles
from src.app import response as R
from src.app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    SendCodeRequest,
    RefreshTokenRequest,
    LogoutRequest,
    ForgotPasswordRequest,
    AuthTokenPairVO,
    UserCreateResultVO,
    CaptchaVO,
)
from src.app.schemas.user import CurrentUserInfoVO
from src.app.schemas.errors import BadRequestError
from src.services import AuthService, UserService
from src.infra.jwt import JWTError
from src.infra.captcha import Captcha
from src.infra.email import EmailCode


router = APIRouter(prefix="/api/authserver", tags=["认证"])


# ========== 登录 ==========

@router.post("/login")
async def login(
    req: LoginRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(ip_rate_limit("login", max_count=10, window_seconds=60)),
):
    """用户登录"""
    if not req.captchaId or not req.verifyCode:
        raise BadRequestError("请完成图形验证码")
    is_valid, err = await Captcha.verify(req.captchaId, req.verifyCode)
    if not is_valid:
        raise BadRequestError(err)

    user, access_token, refresh_token = await AuthService.login(
        db, req.username, req.password
    )
    return R.success_resp(
        AuthTokenPairVO(
            accessToken=access_token,
            refreshToken=refresh_token,
        ).model_dump()
    )


@router.post("/admin/login")
async def admin_login(
    req: LoginRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(ip_rate_limit("admin_login", max_count=10, window_seconds=60)),
):
    """管理员登录"""
    if not req.captchaId or not req.verifyCode:
        raise BadRequestError("请完成图形验证码")
    is_valid, err = await Captcha.verify(req.captchaId, req.verifyCode)
    if not is_valid:
        raise BadRequestError(err)

    user, access_token, refresh_token = await AuthService.admin_login(
        db, req.username, req.password
    )
    return R.success_resp(
        AuthTokenPairVO(
            accessToken=access_token,
            refreshToken=refresh_token,
        ).model_dump()
    )


# ========== 注册 ==========

@router.post("/register", status_code=201)
async def register(
    req: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """用户注册"""
    ok, err = await EmailCode.verify(req.username, "register", req.code)
    if not ok:
        raise BadRequestError(err)

    user = await AuthService.register(db, req)
    return R.created_resp(
        UserCreateResultVO(userId=user.id, username=user.username).model_dump()
    )


# ========== Token 刷新/登出 ==========

@router.post("/refresh")
async def refresh_token(
    req: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    """刷新Token"""
    new_access, new_refresh = await AuthService.refresh(db, req.refreshToken)
    return R.success_resp(
        AuthTokenPairVO(
            accessToken=new_access,
            refreshToken=new_refresh,
        ).model_dump()
    )


@router.post("/logout")
async def logout(req: LogoutRequest):
    """登出，撤销 refresh token"""
    await AuthService.revoke_refresh_token(req.refreshToken)
    return R.success_resp(msg="已登出")


# ========== 邮箱验证码 ==========

@router.post("/sendEmailCode")
async def send_email_code(
    req: SendCodeRequest,
    _: None = Depends(ip_rate_limit("send_email_code", max_count=5, window_seconds=60)),
):
    """发送邮箱验证码（注册用）"""
    ok, err = await EmailCode.send(req.email, req.type)
    if not ok:
        return R.too_many_requests_resp(err)
    return R.success_resp(msg="验证码已发送")


@router.post("/sendResetCode")
async def send_reset_code(
    req: SendCodeRequest,
    _: None = Depends(ip_rate_limit("send_reset_code", max_count=5, window_seconds=60)),
):
    """发送重置密码验证码"""
    ok, err = await EmailCode.send(req.email, "reset")
    if not ok:
        return R.too_many_requests_resp(err)
    return R.success_resp(msg="验证码已发送")


@router.post("/reset-password")
async def reset_password(
    req: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """重置密码（schema 内部已经校验两次密码一致）"""
    ok, err = await EmailCode.verify(req.username, "reset", req.code)
    if not ok:
        raise BadRequestError(err)

    await AuthService.reset_password(db, req)
    return R.success_resp(msg="密码重置成功")


# ========== 图形验证码 ==========

@router.get("/captcha/generate")
async def get_captcha(
    _: None = Depends(ip_rate_limit("captcha", max_count=20, window_seconds=60)),
):
    """获取图形验证码"""
    captcha_id, base64_image = await Captcha.generate()
    return R.success_resp(
        CaptchaVO(
            captchaId=captcha_id,
            base64=f"data:image/png;base64,{base64_image}",
        ).model_dump()
    )


# ========== 当前用户 ==========

@router.get("/me")
async def get_current_user_info(db: AsyncSession = Depends(get_db)):
    """获取当前用户信息"""
    user = await UserService.get_user_by_id_or_raise(db, get_user_id())
    return R.success_resp(
        CurrentUserInfoVO.from_orm_to_vo(
            user,
            roles=get_user_roles(),
        ).model_dump()
    )
