"""认证服务"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from datetime import datetime

from src.infra.jwt import (
    create_token,
    create_refresh_token,
    verify_token,
    hash_password,
    verify_password,
    JWTError,
)
from src.infra.redis import RedisCache, get_redis
from src.models import User, Role, UserRole
from src.services.rbac_service import RbacService


class AuthService:
    """认证服务"""

    @staticmethod
    async def register(
        db: AsyncSession,
        username: str,
        password: str,
    ) -> User:
        """注册用户（自动分配 user 角色）"""
        result = await db.execute(
            select(User).where(User.username == username)
        )
        if result.scalar_one_or_none():
            raise ValueError("用户名已存在")

        user = User(
            username=username,
            password=hash_password(password),
            status="active",
        )
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
            raise ValueError("用户名或密码错误")

        if not verify_password(password, user.password):
            raise ValueError("用户名或密码错误")

        if user.status != "active":
            raise ValueError("账户已被禁用")

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
            raise ValueError("用户名或密码错误")

        if not verify_password(password, user.password):
            raise ValueError("用户名或密码错误")

        if user.status != "active":
            raise ValueError("账户已被禁用")

        # 鉴权：是否有管理端登录资格
        is_whitelist = RbacService._is_admin(user.username)
        if not is_whitelist and not await RbacService.has_any_role(
            db, user.id, "super_admin", "admin", "reviewer"
        ):
            raise ValueError("无管理端登录权限")

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
        """
        # 1. 解析并验证 refresh token
        payload = verify_token(refresh_token)
        if payload.get("type") != "refresh":
            raise JWTError("无效的 refresh token 类型")

        jti = payload.get("jti")
        if not jti:
            raise JWTError("Refresh token 缺少 jti")

        # 2. 检查是否已撤销
        redis = await get_redis()
        cache = RedisCache(redis)
        if await cache.is_refresh_token_revoked(jti):
            raise JWTError("Refresh token 已失效")

        # 3. 检查用户是否仍然有效
        user_id = payload.get("userId")
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user or user.status != "active":
            raise JWTError("用户不存在或已禁用")

        # 4. 撤销旧 refresh token (rotation)
        await cache.revoke_refresh_token(jti)

        # 5. 签发新 token 对（仅身份信息）
        new_access_token = create_token(user_id=user.id, username=user.username)
        new_refresh_token = create_refresh_token(user_id=user.id, username=user.username)
        return new_access_token, new_refresh_token

    @staticmethod
    async def revoke_refresh_token(refresh_token: str) -> None:
        """撤销指定的 refresh token（登出时调用）"""
        payload = verify_token(refresh_token)
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
        username: str,
        new_password: str,
    ) -> bool:
        """重置密码"""
        result = await db.execute(
            select(User).where(User.username == username)
        )
        user = result.scalar_one_or_none()

        if not user:
            raise ValueError("用户不存在")

        user.password = hash_password(new_password)
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
