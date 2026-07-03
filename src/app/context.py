"""请求用户上下文 - 基于 ContextVar 的异步安全存储（类似 Java ThreadLocal）

使用方式：
  中间件写入：set_user({user_id, username, is_admin, roles, permissions})
  业务代码读取：get_user_id() / get_username() / get_user_permissions() / ...
  请求结束清理：clear_user()
"""
from contextvars import ContextVar
from typing import Optional, Dict, Any, List

_user: ContextVar[Optional[Dict[str, Any]]] = ContextVar("user", default=None)


def set_user(data: Optional[Dict[str, Any]]) -> None:
    _user.set(data)


def clear_user() -> None:
    _user.set(None)


def get_user_id() -> Optional[int]:
    u = _user.get()
    return u.get("user_id") if u else None


def get_username() -> Optional[str]:
    u = _user.get()
    return u.get("username") if u else None


def get_user_roles() -> List[Dict[str, Any]]:
    u = _user.get()
    return u.get("roles", []) if u else []


def get_user_permissions() -> List[str]:
    u = _user.get()
    return u.get("permissions", []) if u else []


def has_permission(code: str) -> bool:
    perms = get_user_permissions()
    return "*" in perms or code in perms
