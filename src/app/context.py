"""用户上下文 - 基于 ContextVar 的异步安全存储

类似 Java 的 ThreadLocal，但支持异步
"""
from contextvars import ContextVar
from typing import Optional, Dict, Any, List


# 存储当前用户信息
_current_user: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    'current_user',
    default=None
)


def set_current_user(user: Optional[Dict[str, Any]]) -> None:
    """设置当前用户到请求上下文"""
    _current_user.set(user)


def get_current_user() -> Optional[Dict[str, Any]]:
    """获取当前用户"""
    return _current_user.get()


def clear_current_user() -> None:
    """清除当前用户（请求结束时调用，防止内存泄漏）"""
    _current_user.set(None)


def get_user_permissions() -> List[str]:
    """获取当前用户的权限列表"""
    user = get_current_user()
    if not user:
        return []
    return user.get("permissions", [])


def get_user_id() -> Optional[int]:
    """获取当前用户 ID"""
    user = get_current_user()
    return user.get("user_id") if user else None


def get_username() -> Optional[str]:
    """获取当前用户名"""
    user = get_current_user()
    return user.get("username") if user else None


def get_user_roles() -> List[str]:
    """获取当前用户的角色列表"""
    user = get_current_user()
    if not user:
        return []
    return user.get("roles", [])


def is_system_user() -> bool:
    """检查当前用户是否为 system_user（白名单）"""
    from src.services.rbac_service import RbacService
    username = get_username()
    if not username:
        return False
    return RbacService._is_admin(username)
