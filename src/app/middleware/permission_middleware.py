"""权限校验中间件 - 按需查 Redis，未命中则查 DB"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from sqlalchemy import select
from typing import Optional

from src.app.context import get_user_permissions, is_system_user
from src.models.user import Permission
from src.infra.redis import get_redis

_PUBLIC = "__public__"  # 路径无需权限的 Redis 哨兵值
_REDIS_TTL = 3600  # 缓存 1 小时，兜底防脏数据永久存活


class PermissionMiddleware(BaseHTTPMiddleware):

    # 已认证但无需特定权限的路径
    NO_PERMISSION_PATHS = {
        "/api/authserver/me",
        "/api/authserver/refresh",
        "/api/authserver/logout",
    }

    @staticmethod
    async def get_required_permission(path: str) -> Optional[str]:
        """查 Redis 获取路径所需权限码；未命中则查 DB 并回写 Redis"""
        from src.infra.database import AsyncSessionLocal

        redis = await get_redis()
        key = f"perm:path:{path}"

        cached = await redis.get(key)
        if cached is not None:
            return None if cached == _PUBLIC else cached

        # Redis miss → 查 DB 所有有效绑定
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Permission.route_path, Permission.code)
                .where(Permission.route_path.isnot(None))
                .where(Permission.status == True)
            )
            rows = result.all()

        code = None

        # 1. 精确匹配
        for route_path, perm_code in rows:
            if route_path == path:
                code = perm_code
                break

        # 2. 前缀匹配（动态路由如 /api/users/123 匹配 /api/users/{id}）
        if code is None:
            for route_path, perm_code in rows:
                parts = route_path.rstrip("/").split("/")
                if not any(p.startswith("{") for p in parts):
                    continue
                prefix_parts = []
                for p in parts:
                    if p.startswith("{"):
                        break
                    prefix_parts.append(p)
                prefix = "/".join(prefix_parts)
                if prefix and path.startswith(prefix + "/"):
                    code = perm_code
                    break

        await redis.set(key, code if code else _PUBLIC, ex=_REDIS_TTL)
        return code

    @staticmethod
    async def invalidate_cache():
        """清除所有路径权限缓存（权限变更时调用）"""
        redis = await get_redis()
        async for key in redis.scan_iter("perm:path:*"):
            await redis.delete(key)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if request.method == "OPTIONS":
            return await call_next(request)

        if self._no_permission_required(path):
            return await call_next(request)

        if is_system_user():
            return await call_next(request)

        required_permission = await self.get_required_permission(path)

        if not required_permission:
            return await call_next(request)

        user_permissions = get_user_permissions()
        if self._has_permission(user_permissions, required_permission):
            return await call_next(request)

        return JSONResponse(
            status_code=403,
            content={"code": 403, "msg": f"权限不足，需要: {required_permission}"},
        )

    def _no_permission_required(self, path: str) -> bool:
        if path in self.NO_PERMISSION_PATHS:
            return True
        for bypass in self.NO_PERMISSION_PATHS:
            if path.startswith(bypass + "/"):
                return True
        return False

    def _has_permission(self, user_permissions: list, required: str) -> bool:
        if "*" in user_permissions:
            return True
        return required in user_permissions
