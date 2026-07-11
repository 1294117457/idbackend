"""权限校验中间件

职责（v2 单一）：请求流程编排
1. 公开路径 / OPTIONS → 直接放行
2. 无需权限路径 → 直接放行（AuthMiddleware 已保证已登录）
3. 通过 UserService.load_user_rbac 加载角色/权限写入 ContextVar
4. 通过 RbacService 查询路径所需权限码
5. 鉴权判定 → 放行或 403

⚠️ 不再做账号禁用检测——AuthMiddleware 已校验账号 ACTIVE（见 verify_account_active）。

DB 查询 / 业务逻辑全部委托给 Service 层，中间件只做编排。
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from src.app.context import get_user_id, get_username, set_user, get_user_permissions
from src.app.response import forbidden_resp
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

        # 白名单超管（.env 的 SYSTEM_ACCOUNTS）：跳过 DB 查询，直接给全部权限
        # 这是逃生通道，用于 DB 清空 / RBAC 数据丢失等场景，仍能登录系统
        if is_system_account(username):
            set_user({
                "user_id": user_id,
                "username": username,
                "is_admin": True,
                "roles": [{"roleCode": "super_admin", "roleName": "超级管理员"}],
                "permissions": ["*"],
            })
            return await call_next(request)

        # 从数据库加载用户角色 + 权限（账号状态由 AuthMiddleware 已保证 ACTIVE）
        user_auth = await UserService.load_user_rbac(user_id)
        if user_auth is None:
            # 防御性兜底：理论上不会到这里（AuthMiddleware 已校验 status）
            # 真到这里说明 token 中的 userId 在 DB 不存在（用户已被硬删除）
            return forbidden_resp("权限信息加载失败")
        set_user(user_auth)

        # super_admin 角色短路：
        #   用户在 DB 里被绑定了 super_admin 角色 → 直接给 ["*"]，无需逐项校验
        #   与 SYSTEM_ACCOUNTS 白名单完全独立：
        #     - 白名单：.env 配置，不走 DB
        #     - super_admin 角色：DB role 表里的一行，走 DB
        #   两者都走 "permissions=['*']" 短路，PermissionMiddleware 第 87 行生效
        if any(
            (r.get("roleCode") or r.get("role_code")) == "super_admin"
            for r in user_auth.get("roles", [])
        ):
            user_auth["permissions"] = ["*"]
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
