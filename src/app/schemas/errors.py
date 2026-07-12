"""通用业务异常家族（运行时层）

⚠️ 命名空间说明：本文件位于 src/app/schemas/ 目录，**不是** Pydantic DTO，
而是运行时异常类。混放是为了便于发现（与 DTO/VO 同目录可一次性浏览）。
若之后异常体系膨胀，可整体迁出至 src/app/errors.py。

设计哲学：
- 业务异常只有"语义"（NotFoundError / BadRequestError / ForbiddenError /
  ConflictError / UnauthorizedError）+ "msg" 两件事；http_code 由类决定，
  error_code 是稳定的前端可读代码
- **不鼓励为每种业务错误定义子类**——除非需要带结构化 data 字段
  （如"申请数 + count"的特殊场景）。YAGNI：当前阶段只用这 5 个通用类
- handler 用基类一次性接住全部业务异常（见 middleware/exception_handlers.py）

⚠️ 双 token 场景的 body_code 解耦：
- 业务层 4xx/5xx：body.code = http_code（一对一，handler 默认行为）
- 认证层 401 细分：业务异常携带 `body_code` 字段（解耦 http_code 与 body.code）
  例：AccountDisabledError(http_code=401, body_code=10003)
- exception_handler 优先用 exc.body_code 作为 body.code（见 exception_handlers.py）

命名约定：所有业务异常类均以 `Error` 后缀结尾，便于和领域模型（NotFound /
Conflict 等概念名词）区分。例如 `raise NotFoundError(...)` 一眼即看出"抛异常"。

约定（外部使用）：
    from src.app.schemas.errors import NotFoundError, BadRequestError

    raise NotFoundError(f"分类(id={cid})不存在")
    raise BadRequestError("请求参数错误")
"""
from typing import Optional


class BusinessError(Exception):
    """所有业务异常的根。

    默认 http_code=500（用于未预期的逻辑错误）；正常业务异常应继承下面 5 个语义类。
    """

    http_code: int = 500
    error_code: str = "INTERNAL_ERROR"
    default_message: str = "服务器内部错误"
    # 双 token 场景下，业务异常可携带独立 body_code 字段（解耦 http_code）
    # 默认 None → exception_handler 用 http_code 作为 body.code
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
    """账号被禁用 → HTTP 401 + body.code=10003

    被 auth_service.refresh() 在用户中途被禁用时抛出。
    被 exception_handler 按 body_code=10003 映射响应体。

    设计决策：body_code=10003（与 invalid_token_resp 共享编号，msg 区分提示文案）。
    理由：账号禁用是"身份不可信"的极端态，与 token 篡改/签错共享"身份失效通用桶"，
    前端通过 msg 字段判断弹"账号已被禁用"还是"Token 无效"。
    """

    http_code = 401
    error_code = "ACCOUNT_DISABLED"  # 日志用（不要用于响应体）
    body_code = 10003               # 响应 body.code
    default_message = "账号已被禁用，请联系管理员"


class RefreshTokenExpiredError(BusinessError):
    """refresh_token 过期 → HTTP 401 + body.code=10002

    业务层异常（非 jose 基础设施异常）。
    由 auth_service.refresh() 捕获 jose 的 jwt.ExpiredSignatureError 后重新抛出。
    exception_handler 按 body_code=10002 映射响应体。

    设计：放在 schemas/errors.py 而非 jwt.py。
    access / refresh 是业务概念，jwt 层面只有"过期"一种事实；
    业务路由 expected_type → body_code 应该住在业务层。
    """

    http_code = 401
    error_code = "REFRESH_TOKEN_EXPIRED"  # 日志用
    body_code = 10002                    # 响应 body.code
    default_message = "refresh_token 已过期，请重新登录"


class InvalidTokenError(BusinessError):
    """token 无效 / 类型错 / 篡改 → HTTP 401 + body.code=10003

    与 UnauthorizedError（401/401）的区别：
    - UnauthorizedError: 业务层 401（无身份）
    - InvalidTokenError:  身份不可信（token 篡改/类型错/refresh 失效）

    设计：用于 auth_service.refresh() 各种 refresh 失效场景（除 10002 之外）。
    jwt.py 透传 jose 原生异常（jwt.ExpiredSignatureError / JWTError），
    业务层翻译为 InvalidTokenError，自动映射到 10003。
    """

    http_code = 401
    error_code = "INVALID_TOKEN"  # 日志用
    body_code = 10003            # 响应 body.code
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
