"""认证中间件 - 解析 JWT，设置用户上下文

职责：
1. 检查白名单路径，直接放行
2. 解析 Authorization Header 获取 JWT Token
3. 验证 Token 并设置用户上下文到 ContextVar
4. 没有 token 或 token 无效 → 返回 401（未认证）

注意：权限校验由 PermissionMiddleware 负责
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from src.app.context import set_user, clear_user
from src.app.response import unauthorized_resp
from src.infra.jwt import verify_token, JWTError


class AuthMiddleware(BaseHTTPMiddleware):
    """请求认证中间件 - 只负责验证身份，不负责权限校验"""

    # 白名单路径（无需认证的接口）
    BYPASS_PATHS = [
        # 认证相关
        "/api/authserver/login",
        "/api/authserver/admin/login",
        "/api/authserver/register",
        "/api/authserver/captcha/generate",
        "/api/authserver/sendEmailCode",
        "/api/authserver/sendResetCode",
        "/api/authserver/reset-password",
        # 文档
        "/health",
        "/docs",
        "/openapi.json",
        "/redoc",
    ]

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method.upper()

        # 0. OPTIONS 预检请求直接放行
        if method == "OPTIONS":
            return await call_next(request)

        # 1. 检查白名单 - 直接放行
        if self._is_bypass_path(path):
            return await call_next(request)

        # 2. 获取 Token
        auth_header = request.headers.get("Authorization", "")

        if not auth_header.startswith("Bearer "):
            return unauthorized_resp("请先登录")

        token = auth_header[7:]

        # 3. 解析 JWT
        try:
            payload = verify_token(token)
        except JWTError:
            return unauthorized_resp("Token无效")

        # 4. 构建用户对象（仅身份信息；权限/角色由 PermissionMiddleware 实时判定）
        user = {
            "user_id": payload.get("userId"),
            "username": payload.get("username"),
        }

        set_user(user)
        try:
            return await call_next(request)
        finally:
            clear_user()

    def _is_bypass_path(self, path: str) -> bool:
        """检查路径是否在白名单中"""
        for bypass in self.BYPASS_PATHS:
            if path == bypass or path.startswith(bypass + "/"):
                return True
        return False
