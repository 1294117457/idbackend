"""JWT 工具

异常体系（向后兼容 TokenError / 子类继承自 JWTError）：
- TokenError:                基类，body_code=10003（"Token 无效"）
  - AccessTokenExpiredError:  body_code=10001（access 过期）
  - RefreshTokenExpiredError: body_code=10002（refresh 过期）

调用方根据异常 .body_code 字段映射到 response.py 的对应工厂。
本文件不构造 JSONResponse，保持 jwt.py 是纯基础设施层。
"""
from datetime import datetime, timedelta
from typing import Optional, List
from jose import jwt, JWTError
import hashlib

from .config import get_settings

settings = get_settings()

# 尝试导入 bcrypt，如果失败则使用 hashlib 后备
_bcrypt = None
try:
    import bcrypt
    _bcrypt = bcrypt
except ImportError:
    pass


# ============== 自定义异常 ==============

class TokenError(JWTError):
    """JWT 校验失败的基类，自带 http_code=401 + 默认 body.code=10003（"Token 无效"）

    子异常携带 body_code 字段，由调用方（中间件 / service）映射到 response.py 的工厂。
    本文件不构造 JSONResponse，保持 jwt.py 是纯基础设施层（不依赖 HTTP 框架）。
    """

    http_code: int = 401
    body_code: int = 10003
    default_message: str = "Token 无效"

    def __init__(self, message: str = None):
        super().__init__(message or self.default_message, self.http_code)


class AccessTokenExpiredError(TokenError):
    """access_token 过期 → 由 AuthMiddleware 映射到 access_token_expired_resp()"""

    body_code = 10001
    default_message = "access_token 已过期"


class RefreshTokenExpiredError(TokenError):
    """refresh_token 过期 → 由 AuthService.refresh 映射到 refresh_token_expired_resp()"""

    body_code = 10002
    default_message = "refresh_token 已过期"


# ============== 密码 ==============

def hash_password(password: str) -> str:
    """密码哈希"""
    if _bcrypt:
        return _bcrypt.hashpw(password.encode('utf-8'), _bcrypt.gensalt()).decode('utf-8')
    else:
        # 后备方案
        return hashlib.sha256(password.encode()).hexdigest()


def verify_password(plain: str, hashed: str) -> bool:
    """验证密码"""
    if _bcrypt:
        try:
            return _bcrypt.checkpw(plain.encode('utf-8'), hashed.encode('utf-8'))
        except Exception:
            pass
    # 后备方案
    return hashlib.sha256(plain.encode()).hexdigest() == hashed


# ============== Token 签发 ==============

def create_token(
    user_id: int,
    username: str,
    role: str = "user",
    roles: List[str] = None,
    permissions: List[str] = None,
    expires_hours: Optional[int] = None,
) -> str:
    """创建 access token (短期)

    最小化 payload：仅含身份信息 + 过期。
    权限/角色不在 token 内携带，由 PermissionMiddleware + Redis 实时判定。

    Args:
        user_id: 用户ID
        username: 用户名
        role/roles/permissions: 已废弃，保留仅为兼容旧调用方，不再写入 payload
        expires_hours: 过期时间（小时）
    """
    expire = datetime.utcnow() + timedelta(
        hours=expires_hours or settings.JWT_EXPIRE_HOURS
    )
    payload = {
        "userId": user_id,
        "username": username,
        "type": "access",
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(
    user_id: int,
    username: str,
    role: str = "user",
    expires_days: Optional[int] = None,
) -> str:
    """创建 refresh token (长期)，包含 jti 便于撤销

    Args:
        user_id: 用户ID
        username: 用户名
        role: 已废弃，仅保留兼容
        expires_days: 过期时间（天）
    """
    import uuid
    jti = str(uuid.uuid4())
    expire = datetime.utcnow() + timedelta(
        days=expires_days or settings.JWT_REFRESH_EXPIRE_DAYS
    )
    payload = {
        "userId": user_id,
        "username": username,
        "type": "refresh",
        "jti": jti,
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


# ============== Token 校验 ==============

def verify_token(token: str, expected_type: str = "access") -> dict:
    """校验 token 签名 + 类型 + 过期

    Args:
        token: JWT 字符串
        expected_type: "access" / "refresh"

    Returns:
        payload dict（含 userId / username / type / exp / jti 等）

    Raises:
        AccessTokenExpiredError:  access 过期（仅 expected_type="access" 时，body_code=10001）
        RefreshTokenExpiredError: refresh 过期（仅 expected_type="refresh" 时，body_code=10002）
        TokenError:                签名错 / 篡改（body_code=10003）

    Note:
        - 调用方拿到 payload 后需自己校验 payload["type"] == expected_type
          （auth_middleware 校验 type==access；auth_service.refresh 校验 type==refresh）
        - 本方法不构造 JSONResponse，保持 jwt.py 是纯基础设施层
        - 旧调用 verify_token(token) 不传 expected_type 时默认 "access"，向后兼容

    Examples:
        >>> try:
        ...     payload = verify_token(token, expected_type="access")
        ...     if payload.get("type") != "access":
        ...         raise TokenError("Token 类型错误，期望 access")
        ... except AccessTokenExpiredError:
        ...     return access_token_expired_resp()
        ... except TokenError:
        ...     return invalid_token_resp()
    """
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError:
        if expected_type == "access":
            raise AccessTokenExpiredError() from None
        raise RefreshTokenExpiredError() from None
    except JWTError as e:
        raise TokenError(f"Token 验证失败: {e}") from e