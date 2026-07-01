"""路由导出"""
from .auth import router as auth_router
from .user import router as user_router
from .application import router as application_router
from .template import router as template_router
from .file import router as file_router
from .health import router as health_router

__all__ = [
    "auth_router",
    "user_router",
    "application_router",
    "template_router",
    "file_router",
    "health_router",
]
