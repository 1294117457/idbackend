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
from starlette.responses import JSONResponse

from src.app.context import set_current_user, clear_current_user
from src.infra.jwt import verify_token, JWTError
from src.services.rbac_service import RbacService


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
            return JSONResponse(
                status_code=401,
                content={"code": 401, "msg": "请先登录"}
            )

        token = auth_header[7:]

        # 3. 解析 JWT
        try:
            payload = verify_token(token)
        except JWTError as e:
            return JSONResponse(
                status_code=401,
                content={"code": 401, "msg": "Token无效"}
            )

        # 4. 构建用户对象
        user = {
            "user_id": payload.get("userId"),
            "username": payload.get("username"),
            "roles": payload.get("roles", [payload.get("role", "user")]),
            "permissions": payload.get("permissions", []),
        }

        # 5. system_user 自动授予全部权限
        if RbacService._is_admin(user["username"]):
            user["permissions"] = ["*"]
            user["roles"] = ["super_admin"]

        # 6. 设置到 ContextVar
        set_current_user(user)

        try:
            return await call_next(request)
        finally:
            # 7. 请求结束清除上下文
            clear_current_user()

    def _is_bypass_path(self, path: str) -> bool:
        """检查路径是否在白名单中"""
        for bypass in self.BYPASS_PATHS:
            if path == bypass or path.startswith(bypass + "/"):
                return True
        return False
