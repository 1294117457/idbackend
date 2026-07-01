"""用户路由 - 兼容前端"""
from fastapi import APIRouter, Depends, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional

from src.app.deps import get_db, get_current_user, CurrentUser, require_admin
from src.app.response import success_response, error_response
from src.services import UserService

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

    return success_response({
        "userId": db_user.id,
        "username": db_user.username,
        "phone": db_user.phone,
        "avatar": db_user.avatar,
        "role": db_user.role,
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
):
    """获取我的角色"""
    return success_response({"role": user.role})


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

    return success_response({"role": db_user.role})


@router.post("/{user_id}/roles")
async def assign_user_roles(
    user_id: int,
    role_ids: list[int] = Body(...),
    _: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """分配用户角色 (管理员)"""
    # TODO: 实现角色分配
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
    return success_response({
        "list": [{
            "userId": u.id,
            "username": u.username,
            "phone": u.phone,
            "role": u.role,
            "status": u.status,
            "lastLoginAt": u.last_login_at,
            "fullName": u.full_name,
            "major": u.major,
            "grade": u.grade,
            "graduationYear": u.graduation_year,
        } for u in users],
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
    status: str = Body(..., embed=True),
    _: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """更新用户状态 (管理员)"""
    db_user = await UserService.update_user(db, user_id, status=status)
    if not db_user:
        return error_response("用户不存在", code=404)
    return success_response(msg="状态更新成功")
