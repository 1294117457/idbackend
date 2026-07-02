"""用户菜单 API

提供当前用户可访问的动态菜单：
- GET /api/system/menu/my - 获取当前用户的菜单树
- GET /api/system/user/my/permissions - 获取当前用户的所有权限
- GET /api/system/user/me - 获取当前用户信息
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.deps import get_db, get_current_user, CurrentUser
from src.services.rbac_service import RbacService
from src.app.response import success_response, error_response

router = APIRouter(tags=["菜单管理"])


@router.get("/api/system/menu/my")
async def get_my_menu(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的菜单树

    Returns:
        动态生成的菜单列表，仅包含用户有权限访问的菜单项
    """
    try:
        menus = await RbacService.get_user_menu_tree(db, current_user.user_id)
        return success_response(menus)
    except Exception as e:
        return error_response(str(e))


@router.get("/api/system/user/my/permissions")
async def get_my_permissions(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的所有权限列表

    用于前端按钮级权限控制
    """
    try:
        # 优先使用 ContextVar 中已有的权限（由 AuthMiddleware 设置）
        if current_user.permissions:
            return success_response(current_user.permissions)

        # 如果 ContextVar 没有，从数据库获取
        permissions = await RbacService.get_user_permissions(db, current_user.user_id)
        return success_response(permissions)
    except Exception as e:
        return error_response(str(e))


@router.get("/api/system/user/me")
async def get_current_user_info(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户信息

    返回用户基本信息、角色和权限
    """
    try:
        # 获取完整用户信息
        from src.services.user_service import UserService
        user = await UserService.get_user_by_id(db, current_user.user_id)
        if not user:
            return error_response("用户不存在", code=404)

        return success_response({
            "userId": user.id,
            "username": user.username,
            "fullName": user.full_name,
            "avatar": user.avatar,
            "roles": current_user.role_codes,
            "permissions": current_user.permissions,
        })
    except Exception as e:
        return error_response(str(e))
