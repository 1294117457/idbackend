"""用户菜单 API"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.deps import get_db
from src.app.context import get_user_id, get_user_roles, get_user_permissions
from src.services.rbac_service import RbacService
from src.app import response as R

router = APIRouter(tags=["菜单管理"])


@router.get("/api/system/menu/my")
async def get_my_menu(db: AsyncSession = Depends(get_db)):
    """获取当前用户的菜单树（仅包含用户有权限访问的菜单项）"""
    menus = await RbacService.get_user_menu_tree(db, get_user_permissions())
    return R.success_resp(menus)


@router.get("/api/system/user/my/permissions")
async def get_my_permissions():
    """获取当前用户的所有权限码列表（用于前端按钮级权限控制）"""
    return R.success_resp(get_user_permissions())


@router.get("/api/system/user/me")
async def get_current_user_info(db: AsyncSession = Depends(get_db)):
    """获取当前用户信息（角色 + 权限均来自 ContextVar，无额外 DB 查询）"""
    from src.services.user_service import UserService
    user = await UserService.get_user_by_id(db, get_user_id())
    if not user:
        return R.not_found_resp("用户不存在")

    return R.success_resp({
        "userId": user.id,
        "username": user.username,
        "fullName": user.full_name,
        "avatar": user.avatar,
        "roles": get_user_roles(),
        "permissions": get_user_permissions(),
    })
