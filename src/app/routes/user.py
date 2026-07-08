"""用户路由

学生端:
  GET  /api/users/me        - 获取账户信息
  PUT  /api/users/me        - 更新账户信息

管理端:
  GET  /api/user/me/roles           - 获取我的角色
  GET  /api/user/{user_id}/roles   - 获取用户角色
  POST /api/user/{user_id}/roles    - 分配用户角色
  GET  /api/user/admin/list         - 用户列表
  POST /api/user/admin/create       - 创建用户
  POST /api/user/admin/batch-create - 批量创建用户
  DELETE /api/user/admin/{user_id}  - 删除用户
  PUT  /api/user/admin/{user_id}/status - 更新用户状态
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.deps import get_db
from src.app.context import get_user_id, get_user_roles, get_user_permissions
from src.app import response as R
from src.services import UserProfileService, UserService
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
    user_id = get_user_id()
    if not user_id:
        return R.unauthorized_resp("未登录")

    profile = await UserProfileService.get_profile(db, user_id)
    if not profile:
        return R.error_resp("用户不存在", code=404)

    return R.success_resp(profile)


@users_router.put("/me")
async def update_my_profile(
    req: UpdateUserMeRequest,
    db: AsyncSession = Depends(get_db),
):
    """更新当前用户的账户信息

    可更新字段: phone, full_name, avatar, grade, enrollment_year, graduation_year, major
    不可更新: username, student_id（从 username 提取）
    """
    user_id = get_user_id()
    if not user_id:
        return R.unauthorized_resp("未登录")

    update_data = req.model_dump(exclude_none=True)
    modified = await UserProfileService.update_profile(db, user_id, update_data)

    return R.success_resp(msg="更新成功" if modified else "无变更")


# ========== 管理端用户路由 ==========

# /api/user/* - 管理端用户路由
router = APIRouter(prefix="/api/user", tags=["用户管理"])


@router.get("/me/roles")
async def get_my_roles():
    """获取我的角色（直接从 ContextVar 读取，无额外 DB 查询）"""
    return R.success_resp(get_user_roles())


@router.get("/{user_id}/roles")
async def get_user_roles_admin(
    user_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取用户角色 (管理员)"""
    await UserService.get_user_by_id_or_raise(db, user_id)
    role_ids = await RbacService.get_user_role_ids(db, user_id)
    return R.success_resp(role_ids)


@router.post("/{user_id}/roles")
async def assign_user_roles(
    user_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """分配用户角色 (管理员) —— body: {roleIds: [int, ...]}"""
    role_ids = body.get("roleIds", [])
    await RbacService.assign_roles_to_user(db, user_id, role_ids)
    return R.success_resp(msg="角色分配成功")


@router.get("/admin/list")
async def list_users(
    req: Annotated[UserQueryRequest, Query()],
    db: AsyncSession = Depends(get_db),
):
    """获取用户列表 (管理员)"""
    users, total = await UserService.list_users(db, req)

    items = []
    for u in users:
        roles = await RbacService.get_user_roles(db, u.id)
        items.append(
            UserAdminListItemVO.from_orm_to_vo(u, roles=roles).model_dump()
        )

    page = Page.from_list_to_page(
        items=items,
        total=total,
        page_num=req.pageNum,
        page_size=req.pageSize,
    )
    return R.success_resp(page.model_dump())


@router.delete("/admin/{user_id}")
async def delete_user_admin(
    user_id: int,
    db: AsyncSession = Depends(get_db),
):
    """删除用户 (管理员)"""
    ok = await UserService.delete_user(db, user_id)
    if not ok:
        from src.app.schemas.errors import NotFoundError
        raise NotFoundError(f"用户不存在: id={user_id}")
    return R.success_resp(msg="删除成功")


@router.put("/admin/{user_id}/status")
async def update_user_status_admin(
    user_id: int,
    req: UpdateUserStatusRequest,
    db: AsyncSession = Depends(get_db),
):
    """更新用户状态 (管理员)"""
    user = await UserService.get_user_by_id_or_raise(db, user_id)
    user.status = req.status
    await db.commit()
    await db.refresh(user)
    return R.success_resp(msg="状态更新成功")


@router.post("/admin/create")
async def admin_create_user(
    req: CreateUserRequest,
    db: AsyncSession = Depends(get_db),
):
    """创建用户 (管理员)"""
    from src.app.schemas.errors import ConflictError
    existing = await UserService.get_user_by_username(db, req.username)
    if existing:
        raise ConflictError(f"用户已存在: {req.username}")

    import secrets
    import string

    password = req.password or "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(12)
    )
    user = await UserService.create_user(db, req.username, password)

    if req.role:
        role = await RbacService.get_role_by_code(db, req.role)
        if role:
            await RbacService.assign_roles_to_user(db, user.id, [role.id])

    return R.created_resp(
        {
            "userId": user.id,
            "username": user.username,
            "password": password,
        },
        msg="用户创建成功",
    )


@router.post("/admin/batch-create")
async def admin_batch_create_users(
    req: BatchCreateUserRequest,
    db: AsyncSession = Depends(get_db),
):
    """批量创建用户 (管理员)"""
    import secrets
    import string

    created: list = []
    failed: list = []

    for username in req.usernames:
        try:
            existing = await UserService.get_user_by_username(db, username)
            if existing:
                failed.append({"username": username, "reason": "用户已存在"})
                continue

            password = "".join(
                secrets.choice(string.ascii_letters + string.digits) for _ in range(12)
            )
            user = await UserService.create_user(db, username, password)
            created.append({"username": username, "password": password})
        except Exception as e:
            failed.append({"username": username, "reason": str(e)})

    return R.success_resp({"created": created, "failed": failed})


# ========== 系统级接口（无 prefix） ==========

system_router = APIRouter(tags=["用户"])


@system_router.get("/api/system/user/me")
async def get_current_user_info(db: AsyncSession = Depends(get_db)):
    """获取当前用户信息（角色 + 权限均来自 ContextVar）"""
    user = await UserService.get_user_by_id_or_raise(db, get_user_id())
    return R.success_resp(
        CurrentUserInfoVO.from_orm_to_vo(
            user,
            roles=get_user_roles(),
            permissions=get_user_permissions(),
        ).model_dump()
    )
