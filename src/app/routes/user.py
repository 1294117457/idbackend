"""用户路由 - 兼容前端

架构约定：
- Request 直接喂给 service（service 内部用 req.apply_to 写回 ORM）
- 业务异常 → 由全局 exception_handlers 自动翻译为 HTTP 响应
- VO 由 schema.from_orm_to_vo 生成，路由只用 model_dump() 透传
- 分页场景走 Page.from_list_to_page
- 路由层不再 try/except ValueError
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.deps import get_db
from src.app.context import get_user_id, get_user_roles, get_user_permissions
from src.app import response as R
from src.app.schemas.user import (
    UpdateProfileRequest,
    BindStudentRequest,
    UpdateStudentRequest,
    UpdateUserStatusRequest,
    CreateUserRequest,
    BatchCreateUserRequest,
    UserQueryRequest,
    UserProfileVO,
    UserCompleteInfoVO,
    UserStudentInfoVO,
    UserAdminListItemVO,
    UserAdminListVO,
    CurrentUserInfoVO,
)
from src.services import UserService
from src.services.rbac_service import RbacService
from src.app.schemas.page import Page

# /api/user/** 下的标准用户路由
router = APIRouter(prefix="/api/user", tags=["用户"])

# /api/system/user/me 等系统级用户接口（无 prefix，独立挂载）
system_router = APIRouter(tags=["用户"])


# ========== 用户基本信息 ==========

@router.get("/profile")
async def get_profile(db: AsyncSession = Depends(get_db)):
    """获取用户基本信息"""
    user = await UserService.get_user_by_id_or_raise(db, get_user_id())
    return R.success_resp(
        UserProfileVO.from_orm_to_vo(user, roles=get_user_roles()).model_dump()
    )


@router.put("/profile")
async def update_profile(
    req: UpdateProfileRequest,
    db: AsyncSession = Depends(get_db),
):
    """更新用户基本信息（DTO.apply_to 写回 ORM）"""
    await UserService.update_user_from_request(db, get_user_id(), req)
    return R.success_resp(msg="更新成功")


@router.get("/complete-info")
async def get_complete_info(db: AsyncSession = Depends(get_db)):
    """获取完整用户信息 (包含学生信息)"""
    user = await UserService.get_user_by_id_or_raise(db, get_user_id())
    return R.success_resp(UserCompleteInfoVO.from_orm_to_vo(user).model_dump())


# ========== 学生信息 ==========

@router.post("/student/bind")
async def bind_student(
    req: BindStudentRequest,
    db: AsyncSession = Depends(get_db),
):
    """绑定学生信息"""
    user_id = get_user_id()
    user = await UserService.bind_student_from_request(db, user_id, req)
    return R.success_resp(
        {"userId": user.id, "status": "success"},
        msg="绑定成功",
    )


@router.get("/student/info")
async def get_student_info(db: AsyncSession = Depends(get_db)):
    """获取学生信息"""
    user = await UserService.get_user_by_id_or_raise(db, get_user_id())
    return R.success_resp(UserStudentInfoVO.from_orm_to_vo(user).model_dump())


@router.put("/student/info")
async def update_student_info(
    req: UpdateStudentRequest,
    db: AsyncSession = Depends(get_db),
):
    """更新学生信息"""
    await UserService.update_user_from_request(db, get_user_id(), req)
    return R.success_resp(msg="更新成功")


@router.post("/student/confirm")
async def confirm_student(db: AsyncSession = Depends(get_db)):
    """确认学生身份"""
    await UserService.confirm_student(db, get_user_id())
    return R.success_resp(msg="确认成功")


# ========== 角色相关 ==========

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


# ========== 管理员接口 ==========

@router.get("/admin/list")
async def list_users(
    req: Annotated[UserQueryRequest, Query()],
    db: AsyncSession = Depends(get_db),
):
    """获取用户列表 (管理员) —— service 直接返回 (users, total)，路由组装 Page"""
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
            "password": password,  # 仅在管理员创建场景下回显初始密码
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


# ========== 当前登录用户信息 ==========

@system_router.get("/api/system/user/me")
async def get_current_user_info(db: AsyncSession = Depends(get_db)):
    """获取当前用户信息（角色 + 权限均来自 ContextVar，无额外 DB 查询）"""
    user = await UserService.get_user_by_id_or_raise(db, get_user_id())
    return R.success_resp(
        CurrentUserInfoVO.from_orm_to_vo(
            user,
            roles=get_user_roles(),
            permissions=get_user_permissions(),
        ).model_dump()
    )
