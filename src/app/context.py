"""用户上下文 - 基于 ContextVar 的异步安全存储

类似 Java 的 ThreadLocal，但支持异步。

存储完整用户信息（身份 + 角色 + 权限码），由 PermissionMiddleware 鉴权链路写入，
业务代码和 deps.py 直接读取，无需重复查 DB。
"""
from contextvars import ContextVar
from typing import Optional, Dict, Any, List


# 存储完整用户信息
_current_user: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    'current_user',
    default=None
)


def set_current_user(user: Optional[Dict[str, Any]]) -> None:
    """设置当前用户到请求上下文（仅身份信息，由 AuthMiddleware 调用）"""
    _current_user.set(user)


def get_current_user() -> Optional[Dict[str, Any]]:
    """获取当前用户（仅身份信息）"""
    return _current_user.get()


def clear_current_user() -> None:
    """清除当前用户（请求结束时调用，防止内存泄漏）"""
    _current_user.set(None)


# ========== 完整用户信息（由 PermissionMiddleware 写入）========== #


def set_current_user_full(user: Optional[Dict[str, Any]]) -> None:
    """设置完整用户信息到请求上下文（PermissionMiddleware 调用）"""
    _current_user.set(user)


def get_current_user_full() -> Optional[Dict[str, Any]]:
    """获取完整用户信息（包含 roles / permissions）"""
    return _current_user.get()


def get_user_permissions() -> List[str]:
    """获取当前用户权限码列表"""
    user = _current_user.get()
    return user.get("permissions", []) if user else []


def get_user_roles() -> List[Dict[str, Any]]:
    """获取当前用户角色列表（[{role_id, role_name}, ...]）"""
    user = _current_user.get()
    return user.get("roles", []) if user else []


def has_permission(code: str) -> bool:
    """检查当前用户是否持有指定权限码（含通配符 *）"""
    perms = get_user_permissions()
    return "*" in perms or code in perms


# ========== 兼容旧接口（降级到取 identity 字段）========== #


def get_user_id() -> Optional[int]:
    """获取当前用户 ID"""
    user = _current_user.get()
    return user.get("user_id") if user else None


def get_username() -> Optional[str]:
    """获取当前用户名"""
    user = _current_user.get()
    return user.get("username") if user else None


def is_system_user() -> bool:
    """检查当前用户是否为系统白名单用户（拥有全部权限）"""
    from src.services.rbac_service import RbacService
    username = get_username()
    if not username:
        return False
    return RbacService._is_admin(username)
