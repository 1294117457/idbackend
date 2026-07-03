"""权限校验中间件

职责（单一）：请求流程编排
1. 公开路径 / OPTIONS → 直接放行
2. 无需权限路径 → 直接放行（AuthMiddleware 已保证已登录）
3. 通过 UserService 加载完整用户信息写入 ContextVar
4. 通过 RbacService 查询路径所需权限码
5. 鉴权判定 → 放行或 403

DB 查询 / 业务逻辑全部委托给 Service 层，中间件只做编排。
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from src.app.context import get_user_id, get_username, set_user, get_user_permissions
from src.app.response import unauthorized_resp, forbidden_resp
from src.infra.config import is_system_account
from src.services.user_service import UserService
from src.services.rbac_service import RbacService


class PermissionMiddleware(BaseHTTPMiddleware):

    # 完全公开（无需登录），与 AuthMiddleware.BYPASS_PATHS 保持一致
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

        # 白名单超管：跳过 DB 查询，直接给全部权限
        if is_system_account(username):
            set_user({"user_id": user_id, "username": username, "is_admin": True, "roles": [], "permissions": ["*"]})
            return await call_next(request)

        # 从数据库加载用户状态 + 角色 + 权限
        user_auth = await UserService.load_user_auth_info(user_id)
        if user_auth is None:
            return unauthorized_resp("账号已被禁用，请联系管理员")
        set_user(user_auth)

        # 查路径所需权限码（未绑定则无需校验）
        required = await RbacService.get_path_permission(path)
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
