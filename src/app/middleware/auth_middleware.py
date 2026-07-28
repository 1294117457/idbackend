"""认证中间件 - 解析 JWT，校验账号状态

职责（v4）：
1. 检查白名单路径，直接放行
2. 解析 Authorization Header 获取 JWT Token
3. 校验 token 签名 + 过期（签名错/篡改 → 10003，access 过期 → 10001）
4. 校验 token payload 中的 type 字段（必须是 access；类型错 → 10003）
5. 校验账号状态（DB 一次 SELECT）→ 账号禁用返回 body.code=10003
6. 设置用户上下文到 ContextVar（仅身份信息，不含 RBAC）
7. 失败响应统一从 response.py 工厂 return，不在中间件内构造 JSONResponse

业务 body_code 路由职责：本中间件自己负责 access/refresh 过期的细分映射
（refresh 在本中间件几乎不会触发，但防御性兜底）。
底层 jwt.py 直接透传 jose 原生异常（ExpiredSignatureError / JWTError），
由本中间件按上下文捕获并映射到对应 body_code。

注意：权限校验由 PermissionMiddleware 负责
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from jose import jwt as jose_jwt, JWTError

from src.app.context import set_user, clear_user
from src.app.response import (
    unauthorized_resp,
    access_token_expired_resp,
    refresh_token_expired_resp,
    invalid_token_resp,
    account_disabled_resp,
)
from src.infra.jwt import verify_token
from src.infra.database import get_db
from src.services.user_service import UserService


class AuthMiddleware(BaseHTTPMiddleware):
    """请求认证中间件 - 解析 JWT + 校验账号状态

    细分场景（HTTP 状态码 + body.code 双轨）：
    - 无 Authorization 头 / Bearer 格式错 → 401 + body.code=401
    - access_token 过期                  → 401 + body.code=10001
    - refresh_token 过期（防御性兜底）    → 401 + body.code=10002
    - token 篡改 / 签错 / 类型错          → 401 + body.code=10003
    - 账号被禁用                         → 401 + body.code=10003（msg 区分）

    设计：jwt.py 已不区分 access/refresh 业务异常，本中间件按 context 自行映射。
    """

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
            payload = verify_token(token, expected_type="access")
        except jose_jwt.ExpiredSignatureError:
            return access_token_expired_resp()
        except JWTError:
            return invalid_token_resp()

        # 4. 校验 token 类型
        if payload.get("type") != "access":
            return invalid_token_resp("Token 类型错误，期望 access")

        user_id = payload.get("userId")

        # 5. 校验账号状态（通过 get_db 获取 session）
        async for db in get_db():
            is_active = await UserService.verify_account_active(db, user_id)
            if not is_active:
                return account_disabled_resp()
            break

        # 6. 构建用户对象
        user = {
            "user_id": user_id,
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
