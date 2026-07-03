"""角色管理 API"""
from fastapi import APIRouter, Depends, Body
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional, List

from src.app.deps import get_db
from src.app import response as R
from src.services.rbac_service import RbacService

router = APIRouter(prefix="/api/system/role", tags=["角色管理"])


class RoleCreate(BaseModel):
    roleCode: str
    roleName: str
    description: Optional[str] = None
    sortOrder: int = 0


class RoleUpdate(BaseModel):
    id: int
    roleCode: Optional[str] = None
    roleName: Optional[str] = None
    description: Optional[str] = None
    sortOrder: Optional[int] = None
    status: Optional[int] = None


class RolePermissionAssign(BaseModel):
    roleId: int
    permissionIds: List[int]


@router.get("/list")
async def get_role_list(db: AsyncSession = Depends(get_db)):
    """获取所有角色列表"""
    roles = await RbacService.get_all_roles(db)
    return R.success_resp([{
        "id": role.id,
        "roleCode": role.role_code,
        "roleName": role.role_name,
        "description": role.description,
        "sortOrder": role.sort_order,
        "status": 1 if role.status else 0,
        "isSystem": 1 if role.is_system else 0,
        "createdAt": str(role.created_at) if role.created_at else None,
        "updatedAt": str(role.updated_at) if role.updated_at else None,
    } for role in roles])


@router.get("/{role_id}")
async def get_role_detail(
    role_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取角色详情"""
    role = await RbacService.get_role_by_id(db, role_id)
    if not role:
        return R.not_found_resp("角色不存在")

    permissions = await RbacService.get_role_permissions(db, role_id)

    return R.success_resp({
        "id": role.id,
        "roleCode": role.role_code,
        "roleName": role.role_name,
        "description": role.description,
        "sortOrder": role.sort_order,
        "status": 1 if role.status else 0,
        "isSystem": 1 if role.is_system else 0,
        "createdAt": str(role.created_at) if role.created_at else None,
        "updatedAt": str(role.updated_at) if role.updated_at else None,
        "permissions": [{
            "id": p.id,
            "permissionCode": p.permission_code,
            "permissionName": p.permission_name,
            "routePath": p.api_path,
            "description": p.description,
        } for p in permissions]
    })


@router.post("/create")
async def create_role(
    data: RoleCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建角色"""
    try:
        role = await RbacService.create_role(
            db=db,
            role_code=data.roleCode,
            role_name=data.roleName,
            description=data.description,
            sort_order=data.sortOrder,
        )
        return R.created_resp({
            "id": role.id,
            "roleCode": role.role_code,
            "roleName": role.role_name,
            "description": role.description,
            "sortOrder": role.sort_order,
            "status": 1 if role.status else 0,
            "isSystem": 1 if role.is_system else 0,
        }, msg="角色创建成功")
    except ValueError as e:
        return R.bad_request_resp(str(e))


@router.put("/update")
async def update_role(
    data: RoleUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新角色"""
    try:
        role = await RbacService.update_role(
            db=db,
            role_id=data.id,
            role_code=data.roleCode,
            role_name=data.roleName,
            description=data.description,
            sort_order=data.sortOrder,
            status=bool(data.status) if data.status is not None else None,
        )
        if not role:
            return R.not_found_resp("角色不存在")
        return R.success_resp(msg="角色更新成功")
    except ValueError as e:
        return R.bad_request_resp(str(e))


@router.delete("/{role_id}")
async def delete_role(
    role_id: int,
    db: AsyncSession = Depends(get_db),
):
    """删除角色"""
    try:
        result = await RbacService.delete_role(db, role_id)
        if not result:
            return R.not_found_resp("角色不存在")
        return R.success_resp(msg="角色删除成功")
    except ValueError as e:
        return R.bad_request_resp(str(e))


@router.get("/{role_id}/permissions")
async def get_role_permissions(
    role_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取角色的权限列表"""
    permissions = await RbacService.get_role_permissions(db, role_id)
    return R.success_resp([{
        "id": p.id,
        "permissionCode": p.permission_code,
        "permissionName": p.permission_name,
        "routePath": p.api_path,
        "description": p.description,
        "sortOrder": p.sort_order,
        "status": 1 if p.status else 0,
    } for p in permissions])


@router.post("/assignPermissions")
async def assign_permissions_to_role(
    data: RolePermissionAssign,
    db: AsyncSession = Depends(get_db),
):
    """为角色分配权限"""
    try:
        await RbacService.assign_permissions_to_role(
            db=db,
            role_id=data.roleId,
            permission_ids=data.permissionIds,
        )
        return R.success_resp(msg="权限分配成功")
    except ValueError as e:
        return R.bad_request_resp(str(e))
