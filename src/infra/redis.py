"""Redis 客户端"""

from typing import Optional
from functools import lru_cache
from .config import get_settings

settings = get_settings()

_redis_client = None


def _get_redis_module():
    """延迟导入 redis 模块"""
    import redis.asyncio as aioredis

    return aioredis


async def get_redis():
    """获取 Redis 客户端"""
    global _redis_client
    if _redis_client is None:
        aioredis = _get_redis_module()
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


async def close_redis():
    """关闭 Redis 连接"""
    global _redis_client
    if _redis_client:
        await _redis_client.close()
        _redis_client = None


class RedisCache:
    """Redis 缓存工具"""

    def __init__(self, redis):
        self.redis = redis

    async def get(self, key: str) -> Optional[str]:
        return await self.redis.get(key)

    async def set(
        self,
        key: str,
        value: str,
        expire: int = 3600,
    ) -> bool:
        return await self.redis.set(key, value, ex=expire)

    async def delete(self, key: str) -> int:
        return await self.redis.delete(key)

    async def exists(self, key: str) -> bool:
        return await self.redis.exists(key) > 0

    async def incr(self, key: str) -> int:
        return await self.redis.incr(key)

    async def expire(self, key: str, seconds: int) -> bool:
        return await self.redis.expire(key, seconds)

    async def revoke_refresh_token(self, jti: str) -> None:
        """撤销 refresh token (加入黑名单，过期时间与 token 剩余有效期一致)"""
        await self.redis.setex(f"revoked:{jti}", 86400 * 7, "1")

    async def is_refresh_token_revoked(self, jti: str) -> bool:
        """检查 refresh token 是否已撤销"""
        return await self.redis.exists(f"revoked:{jti}") > 0

    async def store_user_refresh_token(
        self, user_id: int, jti: str, expire_seconds: int
    ) -> None:
        """存储用户的 refresh token jti 到集合，方便批量撤销"""
        key = f"user_refresh_tokens:{user_id}"
        await self.redis.sadd(key, jti)
        await self.redis.expire(key, expire_seconds)

    async def revoke_all_user_refresh_tokens(self, user_id: int) -> int:
        """撤销用户的所有 refresh tokens"""
        key = f"user_refresh_tokens:{user_id}"
        jtis = await self.redis.smembers(key)
        if not jtis:
            return 0
        pipe = self.redis.pipeline()
        for jti in jtis:
            pipe.setex(f"revoked:{jti}", 86400 * 7, "1")
        pipe.delete(key)
        await pipe.execute()
        return len(jtis)

    async def rate_limit(
        self,
        key: str,
        max_count: int,
        window_seconds: int,
    ) -> tuple[bool, int]:
        async with self.redis.pipeline(transaction=True) as pipe:
            await pipe.incr(key)
            await pipe.expire(key, window_seconds)  # 每次都设置，不判断count==1
            count, _ = await pipe.execute()
        remaining = max(0, max_count - count)
        return count <= max_count, remaining


async def get_cache() -> RedisCache:
    """获取 RedisCache 实例（快捷方式）"""
    return RedisCache(await get_redis())
