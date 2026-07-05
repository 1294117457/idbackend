"""路由统一导出

约定：
- 每个子模块（如 user.py）导出 router
- 本文件统一 import 后通过 __all__ 暴露
- main.py 一行 register_all_routes(app) 即可注册全部

新增路由步骤：
1. 在 routes/ 下新建文件，定义 router = APIRouter(...)
2. 在本文件 import 并加入 ROUTERS 列表
"""
# ============== 路由 import ==============
from src.app.routes.auth import router as auth_router
from src.app.routes.user import router as user_router
from src.app.routes.application import router as application_router
from src.app.routes.template import router as template_router
from src.app.routes.file import router as file_router
from src.app.routes.health import router as health_router
from src.app.routes.field_config import router as field_config_router
from src.app.routes.attribute import router as attribute_router
from src.app.routes.proof import router as proof_router
from src.app.routes.demand_template import router as demand_template_router
from src.app.routes.demand_application import router as demand_application_router
from src.app.routes.role import router as role_router
from src.app.routes.permission import router as permission_router
from src.app.routes.menu import router as menu_router
from src.app.routes.system_config import router as system_config_router


# ============== 注册顺序（按业务分组） ==============
# 顺序很重要：路径匹配按注册顺序查找，特殊路由（如 health）放最前
ROUTERS = [
    # 系统
    health_router,
    # 认证
    auth_router,
    # 用户
    user_router,
    # 业务核心
    application_router,
    template_router,
    file_router,
    proof_router,
    # 业务辅助
    field_config_router,
    attribute_router,
    # 需求相关
    demand_template_router,
    demand_application_router,
    # 权限管理
    role_router,
    permission_router,
    menu_router,
    # 系统配置
    system_config_router,
]


def register_all_routes(app) -> None:
    """按 ROUTERS 顺序注册全部路由到 app

    优点：
    - main.py 不再关心路由列表
    - 新增路由只需要改本文件的 ROUTERS
    - 顺序集中可控
    """
    for router in ROUTERS:
        app.include_router(router)


__all__ = [
    # 路由实例（按需单独导入使用）
    "auth_router",
    "user_router",
    "application_router",
    "template_router",
    "file_router",
    "health_router",
    "field_config_router",
    "attribute_router",
    "proof_router",
    "demand_template_router",
    "demand_application_router",
    "role_router",
    "permission_router",
    "menu_router",
    "system_config_router",
    # 注册入口
    "register_all_routes",
]