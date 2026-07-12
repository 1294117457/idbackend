"""认证服务"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from datetime import datetime
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
from src.app.schemas.errors import (
    NotFoundError,
    BadRequestError,
    ConflictError,
    ForbiddenError,
    AccountDisabledError,
    RefreshTokenExpiredError,
    InvalidTokenError,
)
from src.services.rbac_service import RbacService


class AuthService:
    """认证服务"""

    @staticmethod
    async def register(
        db: AsyncSession,
        req,
    ) -> User:
        """注册用户（自动分配 user 角色）

        - 用户名冲突 → ConflictError
        - ORM 构造由 req.to_create_orm() 完成
        """
        result = await db.execute(
            select(User).where(User.username == req.username)
        )
        if result.scalar_one_or_none():
            raise ConflictError(f"用户名已存在: {req.username}")

        user = req.to_create_orm()
        db.add(user)
        await db.flush()

        # 自动分配 user 角色
        result = await db.execute(
            select(Role).where(Role.role_code == "user")
        )
        user_role = result.scalar_one_or_none()
        if user_role:
            user_role_link = UserRole(user_id=user.id, role_id=user_role.id)
            db.add(user_role_link)

        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def login(
        db: AsyncSession,
        username: str,
        password: str,
    ) -> tuple[User, str, str]:
        """登录，返回 (用户, access_token, refresh_token)

        权限/角色不再写入 token，由 PermissionMiddleware + Redis 实时判定。
        """
        result = await db.execute(
            select(User).where(User.username == username)
        )
        user = result.scalar_one_or_none()

        if not user:
            raise BadRequestError("用户名或密码错误")

        if not verify_password(password, user.password):
            raise BadRequestError("用户名或密码错误")

        if user.status != UserStatus.ACTIVE.value:
            raise ForbiddenError("账户已被禁用")

        user.last_login_at = datetime.utcnow().isoformat()
        await db.commit()

        access_token = create_token(user_id=user.id, username=user.username)
        refresh_token = create_refresh_token(user_id=user.id, username=user.username)

        return user, access_token, refresh_token

    @staticmethod
    async def admin_login(
        db: AsyncSession,
        username: str,
        password: str,
    ) -> tuple[User, str, str]:
        """管理员登录，返回 (用户, access_token, refresh_token)

        中间件未持有 token 鉴权，因此登录资格判定放在服务层：
        - 密码正确 + 是白名单用户 / 拥有 super_admin / admin / reviewer 角色 → 放行
        """
        result = await db.execute(
            select(User).where(User.username == username)
        )
        user = result.scalar_one_or_none()

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

        user.last_login_at = datetime.utcnow().isoformat()
        await db.commit()

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

        异常细分（被 exception_handler 按 body_code 映射）：
        - RefreshTokenExpiredError → HTTP 401 + body.code=10002（refresh 过期，业务异常）
        - InvalidTokenError        → 重新 throw BadRequest（业务路由层）
        - AccountDisabledError     → HTTP 401 + body.code=10003（账号被禁用，msg 区分）

        设计：verify_token 直接透传 jose 原生异常（ExpiredSignatureError / JWTError），
        本服务按"refresh 上下文"把 ExpiredSignatureError 翻译为业务异常 RefreshTokenExpiredError，
        把其余 JWTError 翻译为 InvalidTokenError。
        """
        # 1. 解析 refresh token（jose 层抛原生异常；本服务按上下文翻译为业务异常）
        try:
            payload = verify_token(refresh_token, expected_type="refresh")
        except jose_jwt.ExpiredSignatureError:
            # refresh 过期 → 10002
            raise RefreshTokenExpiredError()
        except JWTError as e:
            # refresh 本身就是个 token，无效就是"身份不可信"，映射到 10003（与 access 篡改同号）
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
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise NotFoundError(f"用户不存在: id={user_id}")
        if user.status != UserStatus.ACTIVE.value:
            # 用户中途被禁用 → 撤销所有 refresh token（防止继续 rotate）
            await cache.revoke_all_user_refresh_tokens(user_id)
            raise AccountDisabledError()  # HTTP 401 + body.code=10003

        # 4. 撤销旧 refresh token (rotation)
        await cache.revoke_refresh_token(jti)

        # 5. 签发新 token 对（仅身份信息）
        new_access_token = create_token(user_id=user.id, username=user.username)
        new_refresh_token = create_refresh_token(user_id=user.id, username=user.username)
        return new_access_token, new_refresh_token

    @staticmethod
    async def revoke_refresh_token(refresh_token: str) -> None:
        """撤销指定的 refresh token（登出时调用）"""
        try:
            payload = verify_token(refresh_token, expected_type="refresh")
        except JWTError:
            return  # token 无效或过期，忽略
        if payload.get("type") != "refresh":
            return
        jti = payload.get("jti")
        if not jti:
            return
        redis = await get_redis()
        cache = RedisCache(redis)
        await cache.revoke_refresh_token(jti)

    @staticmethod
    async def revoke_all_user_tokens(user_id: int) -> int:
        """撤销用户所有 refresh tokens（密码修改/账户禁用时调用）"""
        redis = await get_redis()
        cache = RedisCache(redis)
        return await cache.revoke_all_user_refresh_tokens(user_id)

    @staticmethod
    async def reset_password(
        db: AsyncSession,
        req,
    ) -> bool:
        """重置密码（req: ForgotPasswordRequest —— apply_to 内部 hash + 写回）"""
        result = await db.execute(
            select(User).where(User.username == req.username)
        )
        user = result.scalar_one_or_none()

        if not user:
            raise NotFoundError(f"用户不存在: {req.username}")

        req.apply_to(user)
        await db.commit()
        return True

    @staticmethod
    async def get_user_by_id(
        db: AsyncSession,
        user_id: int,
    ) -> Optional[User]:
        """根据ID获取用户"""
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def verify_refresh_token(token: str) -> dict:
        """验证刷新Token"""
        return verify_token(token)
