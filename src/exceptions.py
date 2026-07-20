"""业务异常基类（无 ORM/Schema 依赖，领域层可安全导入）"""
from typing import Optional


class BusinessError(Exception):
    """所有业务异常的根"""

    http_code: int = 500
    error_code: str = "INTERNAL_ERROR"
    default_message: str = "服务器内部错误"
    body_code: Optional[int] = None

    def __init__(self, message: Optional[str] = None):
        self.message = message or self.default_message
        super().__init__(self.message)


class NotFoundError(BusinessError):
    """资源不存在 → 404"""

    http_code = 404
    error_code = "NOT_FOUND"
    default_message = "资源不存在"


class BadRequestError(BusinessError):
    """请求参数错误 / 业务规则不满足 → 400"""

    http_code = 400
    error_code = "BAD_REQUEST"
    default_message = "请求参数错误"


class ForbiddenError(BusinessError):
    """无权限操作 → 403"""

    http_code = 403
    error_code = "FORBIDDEN"
    default_message = "无权操作"


class ConflictError(BusinessError):
    """资源冲突 / 状态机不允许 → 409"""

    http_code = 409
    error_code = "CONFLICT"
    default_message = "资源状态冲突"


class UnauthorizedError(BusinessError):
    """未登录 / token 无效 → 401"""

    http_code = 401
    error_code = "UNAUTHORIZED"
    default_message = "请先登录"


class AccountDisabledError(BusinessError):
    """账号被禁用 → HTTP 401 + body.code=10003"""

    http_code = 401
    error_code = "ACCOUNT_DISABLED"
    body_code = 10003
    default_message = "账号已被禁用，请联系管理员"


class RefreshTokenExpiredError(BusinessError):
    """refresh_token 过期 → HTTP 401 + body.code=10002"""

    http_code = 401
    error_code = "REFRESH_TOKEN_EXPIRED"
    body_code = 10002
    default_message = "refresh_token 已过期，请重新登录"


class InvalidTokenError(BusinessError):
    """token 无效 / 类型错 / 篡改 → HTTP 401 + body.code=10003"""

    http_code = 401
    error_code = "INVALID_TOKEN"
    body_code = 10003
    default_message = "Token 无效"


__all__ = [
    "BusinessError",
    "NotFoundError",
    "BadRequestError",
    "ForbiddenError",
    "ConflictError",
    "UnauthorizedError",
    "AccountDisabledError",
    "RefreshTokenExpiredError",
    "InvalidTokenError",
]
