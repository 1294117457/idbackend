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


__all__ = [
    "BusinessError",
    "NotFoundError",
    "BadRequestError",
    "ForbiddenError",
    "ConflictError",
    "UnauthorizedError",
]