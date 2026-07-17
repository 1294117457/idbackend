from datetime import datetime, timedelta
from typing import Optional, List
from jose import jwt
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
    return jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
    )