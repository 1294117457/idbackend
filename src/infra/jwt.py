"""JWT 工具"""
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


def verify_token(token: str) -> Optional[dict]:
    """验证并返回 payload"""
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError:
        raise JWTError("Token 已过期", 401)
    except JWTError as e:
        raise JWTError(f"Token 验证失败: {e}", 401)
