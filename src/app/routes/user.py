"""用户路由 - 兼容前端"""
from fastapi import APIRouter, Depends, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional

from src.app.deps import get_db, get_current_user, CurrentUser, require_admin
from src.app.response import success_response, error_response
from src.services import UserService
from src.services.rbac_service import RbacService

router = APIRouter(prefix="/api/user", tags=["用户"])


# ========== 请求/响应模型 ==========

class UpdateProfileRequest(BaseModel):
    avatar: Optional[str] = None
    phone: Optional[str] = None


class BindStudentRequest(BaseModel):
    fullName: str
    major: str
    grade: Optional[int] = None
    graduationYear: Optional[int] = None


class UpdateStudentRequest(BaseModel):
    fullName: Optional[str] = None
    major: Optional[str] = None
    grade: Optional[int] = None
    graduationYear: Optional[int] = None


class UpdateUserStatusRequest(BaseModel):
    status: str


class CreateUserRequest(BaseModel):
    username: str
    password: Optional[str] = None
    role: Optional[str] = "user"  # 默认角色代码


class BatchCreateUserRequest(BaseModel):
    usernames: list[str]


# ========== 用户基本信息 ==========

@router.get("/profile")
async def get_profile(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取用户基本信息"""
    db_user = await UserService.get_user_by_id(db, user.user_id)
    if not db_user:
        return error_response("用户不存在", code=404)

    # 获取用户角色列表
    roles = await RbacService.get_user_roles(db, user.user_id)

    return success_response({
        "userId": db_user.id,
        "username": db_user.username,
        "phone": db_user.phone,
        "avatar": db_user.avatar,
        "roles": roles,
        "status": db_user.status,
    })


@router.put("/profile")
async def update_profile(
    request: UpdateProfileRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新用户基本信息"""
    updates = {}
    if request.avatar is not None:
        updates["avatar"] = request.avatar
    if request.phone is not None:
        updates["phone"] = request.phone

    db_user = await UserService.update_user(db, user.user_id, **updates)
    if not db_user:
        return error_response("用户不存在", code=404)

    return success_response(msg="更新成功")


@router.get("/complete-info")
async def get_complete_info(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取完整用户信息 (包含学生信息)"""
    db_user = await UserService.get_user_by_id(db, user.user_id)
    if not db_user:
        return error_response("用户不存在", code=404)

    return success_response({
        "userId": db_user.id,
        "username": db_user.username,
        "phone": db_user.phone,
        "avatar": db_user.avatar,
        "email": db_user.username,
        "studentId": db_user.student_id,
        "fullName": db_user.full_name,
        "major": db_user.major,
        "grade": db_user.grade,
        "graduationYear": db_user.graduation_year,
        "enrollmentYear": db_user.enrollment_year,
        "gpa": db_user.gpa,
        "academicScore": db_user.academic_score,
        "specialtyScore": db_user.specialty_score,
        "comprehensiveScore": db_user.comprehensive_score,
        "isConfirmed": db_user.is_confirmed,
        "demandValue": db_user.demand_value,
        "demandFiles": db_user.demand_files,
    })


# ========== 学生信息 ==========

@router.post("/student/bind")
async def bind_student(
    request: BindStudentRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """绑定学生信息"""
    # 获取用户信息以确定 enrollment_year
    db_user = await UserService.get_user_by_id(db, user.user_id)

    db_user = await UserService.bind_student_info(
        db,
        user.user_id,
        student_id="",  # 学生ID需单独设置
        full_name=request.fullName,
        major=request.major,
        grade=request.grade or 1,
        enrollment_year=request.graduationYear - 4 if request.graduationYear else 2023,
    )
    if not db_user:
        return error_response("用户不存在", code=404)

    return success_response(msg="绑定成功", data={"userId": db_user.id, "status": "success"})


@router.get("/student/info")
async def get_student_info(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取学生信息"""
    db_user = await UserService.get_user_by_id(db, user.user_id)
    if not db_user:
        return error_response("用户不存在", code=404)

    return success_response({
        "studentId": db_user.student_id,
        "enrollmentYear": db_user.enrollment_year,
        "fullName": db_user.full_name,
        "major": db_user.major,
        "grade": db_user.grade,
        "graduationYear": db_user.graduation_year,
        "gpa": db_user.gpa,
        "academicScore": db_user.academic_score,
        "specialtyScore": db_user.specialty_score,
        "comprehensiveScore": db_user.comprehensive_score,
        "isConfirmed": db_user.is_confirmed,
        "demandValue": db_user.demand_value,
        "demandFiles": db_user.demand_files,
    })


@router.put("/student/info")
async def update_student_info(
    request: UpdateStudentRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新学生信息"""
    updates = {}
    if request.fullName is not None:
        updates["full_name"] = request.fullName
    if request.major is not None:
        updates["major"] = request.major
    if request.grade is not None:
        updates["grade"] = request.grade
    if request.graduationYear is not None:
        updates["graduation_year"] = request.graduationYear

    db_user = await UserService.update_user(db, user.user_id, **updates)
    if not db_user:
        return error_response("用户不存在", code=404)

    return success_response(msg="更新成功")


@router.post("/student/confirm")
async def confirm_student(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """确认学生身份"""
    db_user = await UserService.confirm_student(db, user.user_id)
    if not db_user:
        return error_response("用户不存在", code=404)

    return success_response(msg="确认成功")


# ========== 角色相关 ==========

@router.get("/me/roles")
async def get_my_roles(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取我的角色"""
    roles = await RbacService.get_user_roles(db, user.user_id)
    return success_response({"roles": roles})


@router.get("/{user_id}/roles")
async def get_user_roles(
    user_id: int,
    _: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """获取用户角色 (管理员)"""
    db_user = await UserService.get_user_by_id(db, user_id)
    if not db_user:
        return error_response("用户不存在", code=404)

    # 获取角色ID列表
    role_ids = await RbacService.get_user_role_ids(db, user_id)
    return success_response({"roles": role_ids})


@router.post("/{user_id}/roles")
async def assign_user_roles(
    user_id: int,
    body: dict = Body(...),
    _: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """分配用户角色 (管理员)"""
    role_ids = body.get("roleIds", [])
    
    # 调用 RBAC 服务分配角色
    await RbacService.assign_roles_to_user(db, user_id, role_ids)
    
    return success_response(msg="角色分配成功")


# ========== 管理员接口 ==========

@router.get("/admin/list")
async def list_users(
    pageNum: int = Query(1, ge=1, alias="pageNum"),
    pageSize: int = Query(20, ge=1, le=100, alias="pageSize"),
    username: Optional[str] = Query(None),
    fullName: Optional[str] = Query(None, alias="fullName"),
    _: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """获取用户列表 (管理员)"""
    users, total = await UserService.list_users(db, None, pageNum, pageSize)

    # 获取每个用户的角色
    user_list = []
    for u in users:
        roles = await RbacService.get_user_roles(db, u.id)
        user_list.append({
            "userId": u.id,
            "username": u.username,
            "phone": u.phone,
            "roles": roles,
            "status": u.status,
            "lastLoginAt": u.last_login_at,
            "fullName": u.full_name,
            "major": u.major,
            "grade": u.grade,
            "graduationYear": u.graduation_year,
        })

    return success_response({
        "list": user_list,
        "total": total,
        "pageNum": pageNum,
        "pageSize": pageSize,
    })


@router.delete("/admin/{user_id}")
async def delete_user_admin(
    user_id: int,
    _: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """删除用户 (管理员)"""
    result = await UserService.delete_user(db, user_id)
    if not result:
        return error_response("用户不存在", code=404)
    return success_response(msg="删除成功")


@router.put("/admin/{user_id}/status")
async def update_user_status_admin(
    user_id: int,
    request: UpdateUserStatusRequest,
    _: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """更新用户状态 (管理员)"""
    db_user = await UserService.update_user(db, user_id, status=request.status)
    if not db_user:
        return error_response("用户不存在", code=404)
    return success_response(msg="状态更新成功")


@router.post("/admin/create")
async def admin_create_user(
    request: CreateUserRequest,
    _: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """创建用户 (管理员)"""
    # 检查用户是否已存在
    existing = await UserService.get_user_by_username(db, request.username)
    if existing:
        return error_response("用户已存在", code=400)

    # 生成随机密码
    import secrets
    import string
    password = request.password or ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))

    user = await UserService.create_user(db, request.username, password)

    # 分配角色
    if request.role:
        role = await RbacService.get_role_by_code(db, request.role)
        if role:
            await RbacService.assign_roles_to_user(db, user.id, [role.id])

    return success_response({
        "userId": user.id,
        "username": user.username,
    }, msg="用户创建成功")


@router.post("/admin/batch-create")
async def admin_batch_create_users(
    request: BatchCreateUserRequest,
    _: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """批量创建用户 (管理员)"""
    import secrets
    import string

    created = []
    failed = []

    for username in request.usernames:
        try:
            existing = await UserService.get_user_by_username(db, username)
            if existing:
                failed.append({"username": username, "reason": "用户已存在"})
                continue

            password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
            user = await UserService.create_user(db, username, password)
            created.append({"username": username, "password": password})
        except Exception as e:
            failed.append({"username": username, "reason": str(e)})

    return success_response({
        "created": created,
        "failed": failed,
    })
