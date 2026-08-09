"""路由统一导出"""
# ============== 路由 import ==============
from src.app.routes.auth import router as auth_router
from src.app.routes.user import router as user_router, users_router as user_profile_router, system_router as user_system_router
from src.app.routes.application import router as application_router
from src.app.routes.score_data import router as score_data_router
from src.app.routes.template import router as template_router
from src.app.routes.template_category import router as template_category_router
from src.app.routes.extra_info_field import router as extra_info_field_router
from src.app.routes.rule import router as rule_router
from src.app.routes.attribute import router as attribute_router
from src.app.routes.file import router as file_router
from src.app.routes.health import router as health_router
from src.app.routes.proof import router as proof_router
from src.app.routes.role import router as role_router
from src.app.routes.permission import router as permission_router
from src.app.routes.system_config import router as system_config_router
from src.app.routes.embedding import router as embedding_router
from src.app.routes.ai_chat import router as ai_chat_router
from src.app.routes.export import router as export_router


# ============== 注册顺序（按业务分组） ==============
ROUTERS = [
    # 系统
    health_router,
    # 认证
    auth_router,
    # 用户
    user_profile_router,  # /api/users/me
    user_router,          # /api/user/admin/*
    user_system_router,   # /api/system/user/me
    # 业务核心
    application_router,
    score_data_router,
    template_router,
    rule_router,
    attribute_router,
    template_category_router,
    extra_info_field_router,
    file_router,
    proof_router,
    # Embedding 管理
    embedding_router,
    # 权限管理
    role_router,
    permission_router,
    # 系统配置
    system_config_router,
    # 导出
    export_router,
    # AI Chat
    ai_chat_router,
]


def register_all_routes(app) -> None:
    """按 ROUTERS 顺序注册全部路由到 app"""
    for router in ROUTERS:
        app.include_router(router)


__all__ = [
    "auth_router",
    "user_router",
    "user_profile_router",
    "user_system_router",
    "application_router",
    "score_data_router",
    "template_router",
    "rule_router",
    "attribute_router",
    "template_category_router",
    "extra_info_field_router",
    "file_router",
    "health_router",
    "proof_router",
    "role_router",
    "permission_router",
    "system_config_router",
    "embedding_router",
    "ai_chat_router",
    "export_router",
    "register_all_routes",
]