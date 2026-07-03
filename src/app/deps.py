"""依赖注入

- get_db: 数据库会话
- get_current_user: 从 ContextVar 提取完整用户信息（由 PermissionMiddleware 设置）
- CurrentUser: 当前登录用户 dataclass（包含 roles / permissions，不再查 DB）
- ip_rate_limit: IP 限流

鉴权判定已全部收敛到 PermissionMiddleware，路由层不再需要鉴权类 Depends。
"""
from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

from src.infra.database import get_db
from src.infra.jwt import verify_token, JWTError
from src.infra.redis import get_redis, RedisCache

security = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    """当前登录用户（所有字段均从 ContextVar 直接获取，无额外 DB 调用）"""
    user_id: int
    username: str
    is_admin: bool = False
    roles: List[Dict[str, Any]] = None   # [{"role_id": 1, "role_name": "审核员"}, ...]
    permissions: List[str] = None         # ["system:user:list", ...]

    def __post_init__(self):
        if self.roles is None:
            self.roles = []
        if self.permissions is None:
            self.permissions = []

    def has_permission(self, code: str) -> bool:
        """检查是否持有指定权限码（含通配符 *）"""
        return "*" in self.permissions or code in self.permissions


async def get_current_user(
    authorization: Optional[str] = Header(None),
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> CurrentUser:
    """获取当前登录用户

    优先从 ContextVar 获取（由 PermissionMiddleware 在鉴权链路中设置）；
    ContextVar 缺失时回退到 Header 解析 JWT（用于中间件异常穿透场景）。
    """
    from src.app.context import get_current_user_full
    ctx = get_current_user_full()
    if ctx:
        return CurrentUser(
            user_id=ctx["user_id"],
            username=ctx["username"],
            is_admin=ctx.get("is_admin", False),
            roles=ctx.get("roles", []),
            permissions=ctx.get("permissions", []),
        )

    # 兜底：从 JWT token 解析（只含身份信息，不含 roles/permissions）
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    elif credentials:
        token = credentials.credentials

    if not token:
        raise HTTPException(status_code=401, detail="请先登录")

    try:
        payload = verify_token(token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Token无效")

    return CurrentUser(
        user_id=payload.get("userId") or payload.get("user_id", 0),
        username=payload.get("username", ""),
        is_admin=False,
        roles=[],
        permissions=[],
    )


def ip_rate_limit(action: str, max_count: int, window_seconds: int):
    """IP 维度限流 Depends 工厂，超限时直接抛 429"""
    async def _check(request: Request):
        import time as _time
        import sys
        t0 = _time.perf_counter()
        client_ip = request.client.host if request.client else "unknown"
        cache = RedisCache(await get_redis())
        t1 = _time.perf_counter()
        allowed, _ = await cache.rate_limit(
            f"rl:ip:{action}:{client_ip}", max_count=max_count, window_seconds=window_seconds
        )
        t2 = _time.perf_counter()
        sys.stderr.write(f"[rate_limit {action}] get_redis={int((t1-t0)*1000)}ms pipeline={int((t2-t1)*1000)}ms\n")
        sys.stderr.flush()
        if not allowed:
            raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")
    return _check
