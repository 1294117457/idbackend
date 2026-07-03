"""权限校验中间件 - 每次查 DB，完整用户信息写入 ContextVar

设计原则：
- 每次 dispatch 内最多 2 次 DB 查询（path → permission_code，user 完整信息）
- 无 Redis 缓存，零不一致窗口
- AuthMiddleware 先执行（JWT 解析），PermissionMiddleware 后执行（鉴权判定）
- 公共路径 / 白名单用户 / OPTIONS 直接放行
- 鉴权：单 path 所需 permission_code 必须在用户权限集合（含 "*"）中
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from sqlalchemy import select, distinct
from sqlalchemy.orm import selectinload
from typing import Optional, List, Dict, Any

from src.app.context import (
    get_current_user,
    get_user_id,
    get_username,
    is_system_user,
    set_current_user_full,
    get_user_permissions,
)
from src.models.user import User, Permission, RolePermission, UserRole, Role
from src.infra.database import AsyncSessionLocal


_NONE = "__NONE__"   # 哨兵：表示"无任何权限/无需权限"


class PermissionMiddleware(BaseHTTPMiddleware):

    # 完全公开（无需登录）
    PUBLIC_PATHS = {
        "/api/authserver/login",
        "/api/authserver/admin/login",
        "/api/authserver/register",
        "/api/authserver/captcha/generate",
        "/api/authserver/sendEmailCode",
        "/api/authserver/sendResetCode",
        "/api/authserver/reset-password",
        "/health",
        "/docs",
        "/openapi.json",
        "/redoc",
    }

    # 需登录但无需特定权限码（已登录即可；不经过 api_path → code 查表）
    NO_PERMISSION_PATHS = {
        "/api/authserver/me",
        "/api/authserver/refresh",
        "/api/authserver/logout",
        "/api/system/menu/my",
        "/api/system/user/me",
        "/api/system/user/my/permissions",
    }

    @staticmethod
    async def get_required_permission(path: str) -> Optional[str]:
        """查 path 所需权限码（每次查 DB，无缓存）。"""
        async with AsyncSessionLocal() as db:
            # 1. 精确匹配（走 api_path 索引）
            result = await db.execute(
                select(Permission.permission_code)
                .where(Permission.api_path == path)
                .where(Permission.status == True)
                .limit(1)
            )
            code: Optional[str] = result.scalar_one_or_none()

            # 2. 前缀匹配（仅当精确 miss 且 path 中含 { 时）
            if code is None and "{" in path:
                result = await db.execute(
                    select(Permission.permission_code, Permission.api_path)
                    .where(Permission.api_path.isnot(None))
                    .where(Permission.status == True)
                )
                for perm_code, route_path in result.all():
                    if "{" not in route_path:
                        continue
                    prefix = route_path.split("{")[0].rstrip("/")
                    if prefix and path.startswith(prefix + "/"):
                        code = perm_code
                        break

        return code

    @staticmethod
    async def load_user_full_info(user_id: int) -> Dict[str, Any]:
        """一次性 JOIN 查询用户完整信息（身份 + 角色 + 权限码），写入 ContextVar。"""
        async with AsyncSessionLocal() as db:
            user = await db.get(User, user_id)
            if not user:
                return {
                    "user_id": user_id,
                    "username": "",
                    "is_admin": False,
                    "roles": [],
                    "permissions": [],
                }

            # 系统白名单用户（配置中 SYSTEM_ACCOUNTS）
            is_admin = PermissionMiddleware._is_system_account(user.username)

            if is_admin:
                return {
                    "user_id": user.id,
                    "username": user.username,
                    "is_admin": True,
                    "roles": [],
                    "permissions": ["*"],
                }

            # JOIN 查询：用户角色 + 角色权限
            result = await db.execute(
                select(Role.id, Role.role_name, Permission.permission_code)
                .select_from(UserRole)
                .join(Role, UserRole.role_id == Role.id)
                .join(RolePermission, RolePermission.role_id == Role.id)
                .join(Permission, RolePermission.permission_id == Permission.id)
                .where(UserRole.user_id == user_id)
                .where(Role.status == True)
                .where(Permission.status == True)
            )
            rows = result.all()

            # 去重收集
            role_map: Dict[int, str] = {}
            perm_set: set[str] = set()
            for role_id, role_name, perm_code in rows:
                role_map[role_id] = role_name
                perm_set.add(perm_code)

            roles = [{"role_id": rid, "role_name": rname} for rid, rname in role_map.items()]
            permissions = sorted(perm_set)

            return {
                "user_id": user.id,
                "username": user.username,
                "is_admin": False,
                "roles": roles,
                "permissions": permissions,
            }

    @staticmethod
    def _is_system_account(username: str) -> bool:
        """检查用户名是否在系统白名单中（拥有全部权限）"""
        from src.infra.config import get_settings
        settings = get_settings()
        return username in settings.SYSTEM_ACCOUNTS

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # OPTIONS 放行
        if request.method == "OPTIONS":
            return await call_next(request)

        # 完全公开路径
        if self._is_under(path, self.PUBLIC_PATHS):
            return await call_next(request)

        # 需登录但无具体权限码
        if self._is_under(path, self.NO_PERMISSION_PATHS):
            return await call_next(request)

        # AuthMiddleware 已将 {user_id, username} 写入 ContextVar
        # 白名单用户：直接放行（AuthMiddleware 先执行，所以这里能读到）
        if is_system_user():
            return await call_next(request)

        user_id = get_user_id()
        if user_id is None:
            return JSONResponse(
                {"code": 401, "msg": "请先登录"},
                status_code=401,
            )

        # 一次性查询完整用户信息，写入 ContextVar
        user_full = await self.load_user_full_info(user_id)
        set_current_user_full(user_full)

        # 鉴权：解析 path 所需权限码
        required = await self.get_required_permission(path)
        if not required:
            return await call_next(request)

        # 鉴权判定
        user_perms = get_user_permissions()
        if "*" in user_perms or required in user_perms:
            return await call_next(request)

        return JSONResponse(
            {"code": 403, "msg": f"权限不足，需要: {required}"},
            status_code=403,
        )

    @staticmethod
    def _is_under(path: str, prefixes) -> bool:
        if path in prefixes:
            return True
        return any(path.startswith(p + "/") for p in prefixes)
