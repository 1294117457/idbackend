"""依赖注入

- get_db: 数据库会话
- ip_rate_limit: IP 维度限流工厂

认证/鉴权由中间件完成，用户信息通过 src.app.context 直接读取，
路由层不再需要 CurrentUser / get_current_user。
"""
from fastapi import HTTPException, Request

from src.infra.database import get_db as get_db
from src.infra.redis import get_redis, RedisCache


def ip_rate_limit(action: str, max_count: int, window_seconds: int):
    """IP 维度限流 Depends 工厂，超限时直接抛 429"""
    async def _check(request: Request):
        client_ip = request.client.host if request.client else "unknown"
        cache = RedisCache(await get_redis())
        allowed, _ = await cache.rate_limit(
            f"rl:ip:{action}:{client_ip}", max_count=max_count, window_seconds=window_seconds
        )
        if not allowed:
            raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")
    return _check
