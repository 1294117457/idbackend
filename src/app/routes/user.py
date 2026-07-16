
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.dependencies import get_db
from src.app.context import get_user_roles
from src.app import response as R
from src.services import UserService
from src.services.rbac_service import RbacService
from src.app.schemas.user import (
    UpdateUserStatusRequest,
    CreateUserRequest,
    BatchCreateUserRequest,
    UserQueryRequest,
    UserAdminListItemVO,
    UserAdminListVO,
    CurrentUserInfoVO,
    UpdateUserMeRequest,
    UpdateUserExtraInfoRequest,
    AssignUserRolesRequest,
)
from src.app.schemas.page import Page


# ========== 学生端账户信息 ==========

# /api/users/* - 学生端账户信息路由
users_router = APIRouter(prefix="/api/users", tags=["用户账户信息"])


@users_router.get("/me")
async def get_my_profile(
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的账户信息

    返回: id, student_id, username, full_name, phone, avatar, grade, enrollment_year, graduation_year, major
    """
    profile = await UserService.get_current_user_profile(db)
    if not profile:
        return R.unauthorized_resp("未登录")

    return R.query_resp(profile.model_dump())


@users_router.put("/me")
async def update_my_profile(
    req: UpdateUserMeRequest,
    db: AsyncSession = Depends(get_db),
):
    update_data = req.model_dump(exclude_none=True)
    modified = await UserService.update_current_user_profile(db, update_data)

    return R.success_resp(msg="更新成功" if modified else "无变更")


@users_router.put("/me/extra-info")
async def update_my_extra_info(
    req: UpdateUserExtraInfoRequest,
    db: AsyncSession = Depends(get_db),
):
    """更新当前用户的扩展信息（extra_info）"""
    modified = await UserService.update_current_user_extra_info(db, req.extra_info)
    return R.success_resp(msg="保存成功" if modified else "无变更")


# ========== 管理端用户路由 ==========

# /api/user/* - 管理端用户路由
router = APIRouter(prefix="/api/user", tags=["用户管理"])


@router.get("/me/roles")
async def get_my_roles():
    """获取我的角色（直接从 ContextVar 读取，无额外 DB 查询）"""
    return R.query_resp(get_user_roles())


@router.get("/{user_id}/roles")
async def get_user_roles_admin(
    user_id: int,
    db: AsyncSession = Depends(get_db),
):
    role_ids = await UserService.get_user_roles(db, user_id)
    return R.query_resp(role_ids)


@router.post("/{user_id}/roles")
async def assign_user_roles(
    user_id: int,
    req: AssignUserRolesRequest,
    db: AsyncSession = Depends(get_db),
):
    await UserService.assign_user_roles(db, user_id, req.roleIds)
    return R.success_resp(msg="角色分配成功")


@router.get("/admin/list")
async def list_users(
    req: Annotated[UserQueryRequest, Query()],
    db: AsyncSession = Depends(get_db),
):
    users, total, user_roles_map = await UserService.list_users_with_roles(db, req)

    vo_items = [
        UserAdminListItemVO.from_orm_to_vo(user, roles=user_roles_map.get(user.id, []))
        for user in users
    ]
    page = Page.from_list_to_page(
        items=[vo.model_dump() for vo in vo_items],
        total=total,
        page_num=req.pageNum,
        page_size=req.pageSize,
    )
    return R.query_resp(page.model_dump())


@router.delete("/admin/{user_id}")
async def delete_user_admin(
    user_id: int,
    db: AsyncSession = Depends(get_db),
):
    await UserService.delete_user_with_raise(db, user_id)
    return R.success_resp(msg="删除成功")


@router.put("/admin/{user_id}/status")
async def update_user_status_admin(
    user_id: int,
    req: UpdateUserStatusRequest,
    db: AsyncSession = Depends(get_db),
):
    await UserService.update_user_status(db, user_id, req.status)
    return R.success_resp(msg="状态更新成功")


@router.post("/admin/create")
async def admin_create_user(
    req: CreateUserRequest,
    db: AsyncSession = Depends(get_db),
):
    user, raw_password = await UserService.create_user_with_password_gen(
        db, req.username, req.password, req.role
    )

    return R.created_resp(
        {
            "userId": user.id,
            "username": user.username,
            "password": raw_password,
        },
        msg="用户创建成功",
    )


@router.post("/admin/batch-create")
async def admin_batch_create_users(
    req: BatchCreateUserRequest,
    db: AsyncSession = Depends(get_db),
):
    created, failed = await UserService.batch_create_users(db, req.usernames)

    return R.success_resp(
        {"created": created, "failed": failed},
        msg=f"批量创建完成：成功 {len(created)} 个，失败 {len(failed)} 个",
    )


# ========== 系统级接口（无 prefix） ==========

system_router = APIRouter(tags=["用户"])


@system_router.get("/api/system/user/me")
async def get_current_user_info(db: AsyncSession = Depends(get_db)):
    vo = await UserService.get_current_user_full_info(db)
    return R.query_resp(vo.model_dump())
