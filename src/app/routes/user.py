"""用户路由 - 兼容前端"""
from fastapi import APIRouter, Depends, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional

from src.app.deps import get_db
from src.app.context import get_user_id, get_user_roles
from src.app import response as R
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
    role: Optional[str] = "user"


class BatchCreateUserRequest(BaseModel):
    usernames: list[str]


# ========== 用户基本信息 ==========

@router.get("/profile")
async def get_profile(db: AsyncSession = Depends(get_db)):
    """获取用户基本信息"""
    db_user = await UserService.get_user_by_id(db, get_user_id())
    if not db_user:
        return R.not_found_resp("用户不存在")

    return R.success_resp({
        "userId": db_user.id,
        "username": db_user.username,
        "phone": db_user.phone,
        "avatar": db_user.avatar,
        "roles": get_user_roles(),
        "status": db_user.status,
    })


@router.put("/profile")
async def update_profile(
    request: UpdateProfileRequest,
    db: AsyncSession = Depends(get_db),
):
    """更新用户基本信息"""
    updates = {}
    if request.avatar is not None:
        updates["avatar"] = request.avatar
    if request.phone is not None:
        updates["phone"] = request.phone

    db_user = await UserService.update_user(db, get_user_id(), **updates)
    if not db_user:
        return R.not_found_resp("用户不存在")

    return R.success_resp(msg="更新成功")


@router.get("/complete-info")
async def get_complete_info(db: AsyncSession = Depends(get_db)):
    """获取完整用户信息 (包含学生信息)"""
    db_user = await UserService.get_user_by_id(db, get_user_id())
    if not db_user:
        return R.not_found_resp("用户不存在")

    return R.success_resp({
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
    db: AsyncSession = Depends(get_db),
):
    """绑定学生信息"""
    user_id = get_user_id()
    db_user = await UserService.bind_student_info(
        db,
        user_id,
        student_id="",
        full_name=request.fullName,
        major=request.major,
        grade=request.grade or 1,
        enrollment_year=request.graduationYear - 4 if request.graduationYear else 2023,
    )
    if not db_user:
        return R.not_found_resp("用户不存在")

    return R.success_resp({"userId": db_user.id, "status": "success"}, msg="绑定成功")


@router.get("/student/info")
async def get_student_info(db: AsyncSession = Depends(get_db)):
    """获取学生信息"""
    db_user = await UserService.get_user_by_id(db, get_user_id())
    if not db_user:
        return R.not_found_resp("用户不存在")

    return R.success_resp({
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

    db_user = await UserService.update_user(db, get_user_id(), **updates)
    if not db_user:
        return R.not_found_resp("用户不存在")

    return R.success_resp(msg="更新成功")


@router.post("/student/confirm")
async def confirm_student(db: AsyncSession = Depends(get_db)):
    """确认学生身份"""
    db_user = await UserService.confirm_student(db, get_user_id())
    if not db_user:
        return R.not_found_resp("用户不存在")

    return R.success_resp(msg="确认成功")


# ========== 角色相关 ==========

@router.get("/me/roles")
async def get_my_roles():
    """获取我的角色（直接从 ContextVar 读取，无额外 DB 查询）
    返回格式：[{roleCode, roleName}, ...]
    """
    return R.success_resp(get_user_roles())


@router.get("/{user_id}/roles")
async def get_user_roles_admin(
    user_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取用户角色 (管理员)"""
    db_user = await UserService.get_user_by_id(db, user_id)
    if not db_user:
        return R.not_found_resp("用户不存在")

    role_ids = await RbacService.get_user_role_ids(db, user_id)
    return R.success_resp(role_ids)


@router.post("/{user_id}/roles")
async def assign_user_roles(
    user_id: int,
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """分配用户角色 (管理员)"""
    role_ids = body.get("roleIds", [])
    await RbacService.assign_roles_to_user(db, user_id, role_ids)
    return R.success_resp(msg="角色分配成功")


# ========== 管理员接口 ==========

@router.get("/admin/list")
async def list_users(
    pageNum: int = Query(1, ge=1, alias="pageNum"),
    pageSize: int = Query(20, ge=1, le=100, alias="pageSize"),
    username: Optional[str] = Query(None),
    fullName: Optional[str] = Query(None, alias="fullName"),
    db: AsyncSession = Depends(get_db),
):
    """获取用户列表 (管理员)"""
    users, total = await UserService.list_users(db, None, pageNum, pageSize)

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

    return R.success_resp({
        "list": user_list,
        "total": total,
        "pageNum": pageNum,
        "pageSize": pageSize,
    })


@router.delete("/admin/{user_id}")
async def delete_user_admin(
    user_id: int,
    db: AsyncSession = Depends(get_db),
):
    """删除用户 (管理员)"""
    result = await UserService.delete_user(db, user_id)
    if not result:
        return R.not_found_resp("用户不存在")
    return R.success_resp(msg="删除成功")


@router.put("/admin/{user_id}/status")
async def update_user_status_admin(
    user_id: int,
    request: UpdateUserStatusRequest,
    db: AsyncSession = Depends(get_db),
):
    """更新用户状态 (管理员)"""
    db_user = await UserService.update_user(db, user_id, status=request.status)
    if not db_user:
        return R.not_found_resp("用户不存在")
    return R.success_resp(msg="状态更新成功")


@router.post("/admin/create")
async def admin_create_user(
    request: CreateUserRequest,
    db: AsyncSession = Depends(get_db),
):
    """创建用户 (管理员)"""
    existing = await UserService.get_user_by_username(db, request.username)
    if existing:
        return R.bad_request_resp("用户已存在")

    import secrets
    import string
    password = request.password or ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))

    user = await UserService.create_user(db, request.username, password)

    if request.role:
        role = await RbacService.get_role_by_code(db, request.role)
        if role:
            await RbacService.assign_roles_to_user(db, user.id, [role.id])

    return R.created_resp({
        "userId": user.id,
        "username": user.username,
    }, msg="用户创建成功")


@router.post("/admin/batch-create")
async def admin_batch_create_users(
    request: BatchCreateUserRequest,
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

    return R.success_resp({
        "created": created,
        "failed": failed,
    })
