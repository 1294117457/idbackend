"""权限校验中间件

职责：
1. 公开路径 / OPTIONS → 直接放行
2. 无需权限路径 → 直接放行
3. 通过 UserService.load_user_rbac 加载角色/权限写入 ContextVar
4. 通过 RbacService 查询路径所需权限码
5. 鉴权判定 → 放行或 403

DB 查询 / 业务逻辑全部委托给 Service 层，中间件只做编排。
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from src.app.context import get_user_id, get_username, set_user, get_user_permissions
from src.app.response import forbidden_resp
from src.infra.config import is_system_account
from src.infra.database import get_db
from src.services.user_service import UserService
from src.services.rbac_service import RbacService


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
        "/metrics",   # Prometheus scrape 端点
    }

    # 已登录即可访问，不校验具体权限码
    NO_PERMISSION_PATHS = {
        "/api/authserver/me",
        "/api/authserver/refresh",
        "/api/authserver/logout",
    }

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if request.method == "OPTIONS":
            return await call_next(request)

        if self._is_under(path, self.PUBLIC_PATHS):
            return await call_next(request)

        if self._is_under(path, self.NO_PERMISSION_PATHS):
            return await call_next(request)

        # AuthMiddleware 已验证 JWT，user_id / username 此时必定非 None
        user_id = get_user_id()
        username = get_username()

        # 白名单超管：跳过 DB 查询
        if is_system_account(username):
            set_user({
                "user_id": user_id,
                "username": username,
                "is_admin": True,
                "roles": [{"roleCode": "super_admin", "roleName": "超级管理员"}],
                "permissions": ["*"],
            })
            return await call_next(request)

        # 从数据库加载用户角色 + 权限
        async for db in get_db():
            user_auth = await UserService.load_user_rbac(db, user_id)
            if user_auth is None:
                return forbidden_resp("权限信息加载失败")

            # super_admin 角色短路
            if any(
                (r.get("roleCode") or r.get("role_code")) == "super_admin"
                for r in user_auth.get("roles", [])
            ):
                user_auth["permissions"] = ["*"]

            set_user(user_auth)

            # 查路径所需权限码
            required = await RbacService.get_path_permission(db, path)
            if not required:
                return await call_next(request)

            # 鉴权判定
            user_perms = get_user_permissions()
            if "*" in user_perms or required in user_perms:
                return await call_next(request)

            return forbidden_resp(f"权限不足，需要: {required}")

    @staticmethod
    def _is_under(path: str, prefixes: set) -> bool:
        return path in prefixes or any(path.startswith(p + "/") for p in prefixes)
