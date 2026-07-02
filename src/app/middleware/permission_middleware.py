"""权限校验中间件

职责：
1. 从数据库加载 route_path -> permission code 映射
2. 根据请求路径自动查找需要的权限
3. 放行或拒绝请求（权限不足返回403）

特性：
- 基于 route_path 的自动鉴权，无需在路由上手动声明
- 启动时加载权限映射，并支持热重载
- 白名单路径直接放行
- system_user 自动通过
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from sqlalchemy import select
from typing import Optional, Dict, Set
import asyncio

from src.app.context import get_user_permissions, is_system_user
from src.models.user import Permission


class PermissionMiddleware(BaseHTTPMiddleware):
    """权限校验中间件 - 基于 route_path 自动鉴权"""

    # 无需权限校验的路径（已认证但不需要特定权限）
    NO_PERMISSION_PATHS = {
        "/api/authserver/me",
        "/api/authserver/refresh",
        "/api/authserver/logout",
    }

    # 权限映射缓存：route_path -> permission code
    _route_permission_map: Dict[str, str] = {}
    # 路径前缀映射：用于匹配动态路由如 /api/users/{id}
    _route_prefix_map: Dict[str, str] = {}
    _loaded = False
    _lock = asyncio.Lock()

    @classmethod
    async def load_permission_map(cls, db):
        """从数据库加载 route_path -> permission code 映射"""
        async with cls._lock:
            if cls._loaded:
                return

            result = await db.execute(
                select(Permission.route_path, Permission.code)
                .where(Permission.route_path.isnot(None))
                .where(Permission.status == True)
            )

            route_map = {}
            prefix_map = {}

            for route_path, code in result.all():
                if route_path:
                    # 精确匹配
                    route_map[route_path] = code

                    # 提取路径前缀（去掉末尾的动态部分）
                    # 例如: /api/users/{id} -> /api/users
                    parts = route_path.rstrip("/").split("/")
                    if any(p.startswith("{") or p.isdigit() for p in parts):
                        # 找到最后一个静态部分作为前缀
                        prefix_parts = []
                        for p in reversed(parts):
                            if p.startswith("{") or p.isdigit():
                                break
                            prefix_parts.insert(0, p)
                        if prefix_parts:
                            prefix = "/".join(prefix_parts)
                            if prefix not in prefix_map:
                                prefix_map[prefix] = code

            cls._route_permission_map = route_map
            cls._route_prefix_map = prefix_map
            cls._loaded = True

    @classmethod
    async def reload_permission_map(cls, db):
        """重新加载权限映射（权限变更后调用）"""
        async with cls._lock:
            cls._loaded = False
            await cls.load_permission_map(db)

    @classmethod
    def get_required_permission(cls, path: str, method: str = None) -> Optional[str]:
        """根据请求路径获取需要的权限码

        匹配顺序：
        1. 精确匹配
        2. 路径前缀匹配
        3. 未找到 = 无需权限
        """
        # 1. 精确匹配
        if path in cls._route_permission_map:
            return cls._route_permission_map[path]

        # 2. 路径前缀匹配（用于 /api/users/{id} 类型的路由）
        for prefix, code in cls._route_prefix_map.items():
            if path.startswith(prefix):
                return code

        return None

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 0. OPTIONS 预检请求直接放行
        if request.method == "OPTIONS":
            return await call_next(request)

        # 1. 检查是否需要权限校验（白名单）
        if self._no_permission_required(path):
            return await call_next(request)

        # 2. system_user 直接通过
        if is_system_user():
            return await call_next(request)

        # 3. 自动查找该路径需要的权限
        required_permission = self.get_required_permission(path, request.method)

        # 4. 路径没有绑定权限 = 公开接口，直接通过
        if not required_permission:
            return await call_next(request)

        # 5. 检查用户权限
        user_permissions = get_user_permissions()

        if self._has_permission(user_permissions, required_permission):
            return await call_next(request)

        # 6. 权限不足，拒绝
        return JSONResponse(
            status_code=403,
            content={"code": 403, "msg": f"权限不足，需要: {required_permission}"}
        )

    def _no_permission_required(self, path: str) -> bool:
        """检查是否不需要权限校验"""
        if path in self.NO_PERMISSION_PATHS:
            return True
        # 前缀匹配
        for bypass in self.NO_PERMISSION_PATHS:
            if path.startswith(bypass + "/"):
                return True
        return False

    def _has_permission(self, user_permissions: list, required: str) -> bool:
        """检查是否有权限"""
        if "*" in user_permissions:
            return True
        return required in user_permissions
