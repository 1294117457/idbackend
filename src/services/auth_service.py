"""认证服务"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from datetime import datetime

from src.infra.jwt import create_token, verify_token, hash_password, verify_password, JWTError
from src.infra.redis import RedisCache, get_redis
from src.models import User


class AuthService:
    """认证服务"""

    @staticmethod
    async def register(
        db: AsyncSession,
        username: str,
        password: str,
    ) -> User:
        """注册用户"""
        # 检查用户名是否存在
        result = await db.execute(
            select(User).where(User.username == username)
        )
        if result.scalar_one_or_none():
            raise ValueError("用户名已存在")

        # 创建用户
        user = User(
            username=username,
            password=hash_password(password),
            status="active",
            role="user",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def login(
        db: AsyncSession,
        username: str,
        password: str,
    ) -> tuple[User, str]:
        """登录"""
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

        # 更新最后登录时间
        user.last_login_at = datetime.utcnow().isoformat()
        await db.commit()

        # 生成 token
        token = create_token(
            user_id=user.id,
            username=user.username,
            role=user.role,
        )

        return user, token

    @staticmethod
    async def send_verification_code(
        email: str,
        code_type: str,
        expire_minutes: int = 5,
    ) -> str:
        """发送验证码"""
        from infra.email import generate_code

        code = generate_code()

        # 存储到 Redis
        redis = await get_redis()
        cache = RedisCache(redis)
        key = f"email_code:{code_type}:{email}"
        await cache.set(code, expire=expire_minutes * 60)

        # TODO: 实际发送邮件
        print(f"[DEBUG] 验证码 {code} 已发送给 {email}")

        return code

    @staticmethod
    async def verify_code(
        email: str,
        code_type: str,
        input_code: str,
    ) -> bool:
        """验证验证码"""
        redis = await get_redis()
        cache = RedisCache(redis)
        key = f"email_code:{code_type}:{email}"
        stored_code = await cache.get(key)

        if not stored_code or stored_code != input_code:
            return False

        # 验证成功后删除
        await cache.delete(key)
        return True

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

    @staticmethod
    async def create_token(
        user_id: int,
        username: str,
        role: str,
    ) -> str:
        """创建Token"""
        return create_token(
            user_id=user_id,
            username=username,
            role=role,
        )
