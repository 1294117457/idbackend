"""角色管理 API

提供前端期望的 RBAC 角色管理接口：
- /api/system/role/list - 获取角色列表
- /api/system/role/{id} - 获取角色详情
- /api/system/role/create - 创建角色
- /api/system/role/update - 更新角色
- /api/system/role/{id} - 删除角色
- /api/system/role/{roleId}/permissions - 获取角色权限
- /api/system/role/assignPermissions - 分配权限给角色
"""
from fastapi import APIRouter, Depends, Body
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional, List

from src.app.deps import get_db, get_current_user, CurrentUser, require_admin
from src.app.response import success_response, error_response
from src.services.rbac_service import RbacService

router = APIRouter(prefix="/api/system/role", tags=["角色管理"])


# ========== 请求/响应模型 ==========

class RoleCreate(BaseModel):
    """创建角色请求"""
    roleCode: str
    roleName: str
    description: Optional[str] = None
    sortOrder: int = 0


class RoleUpdate(BaseModel):
    """更新角色请求"""
    id: int
    roleCode: Optional[str] = None
    roleName: Optional[str] = None
    description: Optional[str] = None
    sortOrder: Optional[int] = None
    status: Optional[int] = None


class RolePermissionAssign(BaseModel):
    """角色权限分配请求"""
    roleId: int
    permissionIds: List[int]


# ========== 角色管理接口 ==========

@router.get("/list")
async def get_role_list(
    _: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """获取所有角色列表"""
    try:
        roles = await RbacService.get_all_roles(db)
        return success_response([{
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
    except Exception as e:
        return error_response(str(e))


@router.get("/{role_id}")
async def get_role_detail(
    role_id: int,
    _: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """获取角色详情"""
    try:
        role = await RbacService.get_role_by_id(db, role_id)
        if not role:
            return error_response("角色不存在", code=404)

        # 获取角色权限
        permissions = await RbacService.get_role_permissions(db, role_id)

        return success_response({
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
                "permissionCode": p.code,
                "permissionName": p.name,
                "routePath": p.route_path,
                "description": p.description,
            } for p in permissions]
        })
    except Exception as e:
        return error_response(str(e))


@router.post("/create")
async def create_role(
    data: RoleCreate,
    _: CurrentUser = Depends(require_admin),
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
        return success_response({
            "id": role.id,
            "roleCode": role.role_code,
            "roleName": role.role_name,
            "description": role.description,
            "sortOrder": role.sort_order,
            "status": 1 if role.status else 0,
            "isSystem": 1 if role.is_system else 0,
        }, msg="角色创建成功")
    except ValueError as e:
        return error_response(str(e), code=400)
    except Exception as e:
        return error_response(str(e))


@router.put("/update")
async def update_role(
    data: RoleUpdate,
    _: CurrentUser = Depends(require_admin),
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
            return error_response("角色不存在", code=404)
        return success_response(msg="角色更新成功")
    except Exception as e:
        return error_response(str(e))


@router.delete("/{role_id}")
async def delete_role(
    role_id: int,
    _: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """删除角色"""
    try:
        result = await RbacService.delete_role(db, role_id)
        if not result:
            return error_response("角色不存在", code=404)
        return success_response(msg="角色删除成功")
    except ValueError as e:
        return error_response(str(e), code=400)
    except Exception as e:
        return error_response(str(e))


# ========== 角色权限分配 ==========

@router.get("/{role_id}/permissions")
async def get_role_permissions(
    role_id: int,
    _: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """获取角色的权限列表"""
    try:
        permissions = await RbacService.get_role_permissions(db, role_id)
        return success_response([{
            "id": p.id,
            "permissionCode": p.code,
            "permissionName": p.name,
            "routePath": p.route_path,
            "description": p.description,
            "sortOrder": p.sort_order,
            "status": 1 if p.status else 0,
        } for p in permissions])
    except Exception as e:
        return error_response(str(e))


@router.post("/assignPermissions")
async def assign_permissions_to_role(
    data: RolePermissionAssign,
    _: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """为角色分配权限"""
    try:
        await RbacService.assign_permissions_to_role(
            db=db,
            role_id=data.roleId,
            permission_ids=data.permissionIds,
        )
        return success_response(msg="权限分配成功")
    except ValueError as e:
        return error_response(str(e), code=400)
    except Exception as e:
        return error_response(str(e))
