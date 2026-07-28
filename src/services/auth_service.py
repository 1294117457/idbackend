"""认证服务"""
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from datetime import datetime, timezone
from jose import jwt as jose_jwt, JWTError

from src.infra.jwt import (
    create_token,
    create_refresh_token,
    verify_token,
    verify_password,
)
from src.infra.redis import RedisCache, get_redis
from src.infra.config import is_system_account
from src.models import User, Role, UserRole
from src.models.user import UserStatus
from src.repositories.user_repo import UserRepository
from src.repositories.role_repo import RoleRepository
from src.app.schemas.errors import (
    NotFoundError,
    BadRequestError,
    ConflictError,
    ForbiddenError,
    AccountDisabledError,
    RefreshTokenExpiredError,
    InvalidTokenError,
)
from src.app.schemas.auth import UserCreateResultVO
from src.services.rbac_service import RbacService


class AuthService:
    """认证服务"""

    @staticmethod
    async def register(
        db: AsyncSession,
        req,
        email_code: str,
    ) -> UserCreateResultVO:
        """注册用户（自动分配 user 角色）

        - 邮箱验证码校验
        - 用户名冲突 → ConflictError
        - ORM 构造由 req.to_create_orm() 完成
        - 返回 UserCreateResultVO
        """
        from src.infra.email import EmailCode

        ok, err = await EmailCode.verify(req.username, "register", email_code)
        if not ok:
            raise BadRequestError(err)

        existing = await UserRepository.get_by_username(db, req.username)
        if existing:
            raise ConflictError(f"用户名已存在: {req.username}")

        user = req.to_create_orm()
        user = await UserRepository.insert(db, user)

        # 自动分配 user 角色
        user_role = await RoleRepository.get_by_code(db, "user")
        if user_role:
            db.add(UserRole(user_id=user.id, role_id=user_role.id))
            await db.flush()

        return UserCreateResultVO.from_user(user)

    @staticmethod
    async def login(
        db: AsyncSession,
        username: str,
        password: str,
        captcha_id: str | None = None,
        verify_code: str | None = None,
    ) -> tuple[User, str, str]:
        """登录，返回 (用户, access_token, refresh_token)

        - 支持可选的图形验证码校验
        - 权限/角色不再写入 token，由 PermissionMiddleware + Redis 实时判定
        """
        from src.infra.captcha import Captcha

        if captcha_id and verify_code:
            is_valid, err = await Captcha.verify(captcha_id, verify_code)
            if not is_valid:
                raise BadRequestError(err)

        user = await UserRepository.get_by_username(db, username)

        if not user:
            raise BadRequestError("用户名或密码错误")

        if not verify_password(password, user.password):
            raise BadRequestError("用户名或密码错误")

        if user.status != UserStatus.ACTIVE.value:
            raise ForbiddenError("账户已被禁用")

        user.last_login_at = datetime.now(timezone.utc).isoformat()
        await db.flush()

        access_token = create_token(user_id=user.id, username=user.username)
        refresh_token = create_refresh_token(user_id=user.id, username=user.username)

        return user, access_token, refresh_token

    @staticmethod
    async def admin_login(
        db: AsyncSession,
        username: str,
        password: str,
        captcha_id: str | None = None,
        verify_code: str | None = None,
    ) -> tuple[User, str, str]:
        """管理员登录，返回 (用户, access_token, refresh_token)

        - 支持可选的图形验证码校验
        - 中间件未持有 token 鉴权，因此登录资格判定放在服务层：
          密码正确 + 是白名单用户 / 拥有 super_admin / admin / reviewer 角色 → 放行
        """
        from src.infra.captcha import Captcha

        if captcha_id and verify_code:
            is_valid, err = await Captcha.verify(captcha_id, verify_code)
            if not is_valid:
                raise BadRequestError(err)

        user = await UserRepository.get_by_username(db, username)

        if not user:
            raise BadRequestError("用户名或密码错误")

        if not verify_password(password, user.password):
            raise BadRequestError("用户名或密码错误")

        if user.status != UserStatus.ACTIVE.value:
            raise ForbiddenError("账户已被禁用")

        # 鉴权：白名单超管，或拥有 super_admin / admin / reviewer 角色之一
        if not is_system_account(user.username) and not await RbacService.has_any_role(
            db, user.id, "super_admin", "admin", "reviewer"
        ):
            raise ForbiddenError("无管理端登录权限")

        user.last_login_at = datetime.now(timezone.utc).isoformat()
        await db.flush()

        access_token = create_token(user_id=user.id, username=user.username)
        refresh_token = create_refresh_token(user_id=user.id, username=user.username)

        return user, access_token, refresh_token

    @staticmethod
    async def refresh(
        db: AsyncSession,
        refresh_token: str,
    ) -> tuple[str, str]:
        """刷新 token，返回 (新的 access_token, 新的 refresh_token)

        不再查询角色/权限，新 token 只含身份信息。
        """
        # 1. 解析 refresh token
        try:
            payload = verify_token(refresh_token, expected_type="refresh")
        except jose_jwt.ExpiredSignatureError:
            raise RefreshTokenExpiredError()
        except JWTError as e:
            raise InvalidTokenError(f"refresh_token 无效: {e}")

        if payload.get("type") != "refresh":
            raise InvalidTokenError("Token 类型错误，期望 refresh")

        jti = payload.get("jti")
        if not jti:
            raise InvalidTokenError("Refresh token 缺少 jti")

        # 2. 检查是否已撤销
        redis = await get_redis()
        cache = RedisCache(redis)
        if await cache.is_refresh_token_revoked(jti):
            raise InvalidTokenError("Refresh token 已失效")

        # 3. 检查用户是否仍然有效
        user_id = payload.get("userId")
        user = await UserRepository.get_by_id(db, user_id)
        if not user:
            raise NotFoundError(f"用户不存在: id={user_id}")
        if user.status != UserStatus.ACTIVE.value:
            await cache.revoke_all_user_refresh_tokens(user_id)
            raise AccountDisabledError()

        # 4. 撤销旧 refresh token (rotation)
        await cache.revoke_refresh_token(jti)

        # 5. 签发新 token 对
        new_access_token = create_token(user_id=user.id, username=user.username)
        new_refresh_token = create_refresh_token(user_id=user.id, username=user.username)
        return new_access_token, new_refresh_token

    @staticmethod
    async def revoke_refresh_token(refresh_token: str) -> None:
        """撤销指定的 refresh token（登出时调用）"""
        try:
            payload = verify_token(refresh_token, expected_type="refresh")
        except JWTError:
            return
        if payload.get("type") != "refresh":
            return
        jti = payload.get("jti")
        if not jti:
            return
        redis = await get_redis()
        cache = RedisCache(redis)
        await cache.revoke_refresh_token(jti)

    @staticmethod
    async def send_email_code(
        email: str,
        email_type: str,
        captcha_id: str | None = None,
        captcha_code: str | None = None,
    ) -> bool:
        """发送邮箱验证码"""
        from src.infra.captcha import Captcha

        if captcha_id and captcha_code:
            is_valid, err = await Captcha.verify(captcha_id, captcha_code)
            if not is_valid:
                raise BadRequestError(err)

        from src.infra.email import EmailCode
        ok, _ = await EmailCode.send(email, email_type)
        return ok

    @staticmethod
    async def revoke_all_user_tokens(user_id: int) -> int:
        """撤销用户所有 refresh tokens"""
        redis = await get_redis()
        cache = RedisCache(redis)
        return await cache.revoke_all_user_refresh_tokens(user_id)

    @staticmethod
    async def reset_password(
        db: AsyncSession,
        req,
    ) -> bool:
        """重置密码"""
        from src.infra.email import EmailCode

        ok, err = await EmailCode.verify(req.username, "reset", req.code)
        if not ok:
            raise BadRequestError(err)

        user = await UserRepository.get_by_username(db, req.username)
        if not user:
            raise NotFoundError(f"用户不存在: {req.username}")

        req.apply_to(user)
        await db.flush()
        return True

    @staticmethod
    async def get_user_by_id(
        db: AsyncSession,
        user_id: int,
    ) -> Optional[User]:
        """根据ID获取用户"""
        return await UserRepository.get_by_id(db, user_id)

    @staticmethod
    async def verify_refresh_token(token: str) -> dict:
        """验证刷新Token"""
        return verify_token(token)
