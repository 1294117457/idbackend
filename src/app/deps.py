"""依赖注入"""
from fastapi import Depends, HTTPException, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from dataclasses import dataclass
from typing import Optional

from infra.database import get_db
from infra.jwt import verify_token, JWTError
from infra.config import get_settings

settings = get_settings()
security = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    """当前登录用户"""
    user_id: int
    username: str
    role: str


async def get_current_user(
    authorization: Optional[str] = Header(None),
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> CurrentUser:
    """获取当前登录用户"""
    # 从 Authorization header 获取 token
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    elif credentials:
        token = credentials.credentials

    if not token:
        raise HTTPException(status_code=401, detail="未登录，请先登录")

    try:
        payload = verify_token(token)
    except JWTError as e:
        raise HTTPException(status_code=401, detail=str(e))

    return CurrentUser(
        user_id=payload.get("userId"),
        username=payload.get("username", payload.get("sub", "")),
        role=payload.get("role", "user"),
    )


def require_role(*allowed_roles: str):
    """角色权限检查装饰器"""
    def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed_roles:
            raise HTTPException(status_code=403, detail="权限不足")
        return user
    return checker


# 常用的角色检查
require_admin = require_role("admin", "super_admin")
require_reviewer = require_role("reviewer", "admin", "super_admin")
