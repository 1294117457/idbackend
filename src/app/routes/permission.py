"""权限管理 API

提供前端期望的 RBAC 权限管理接口：
- /api/system/permission/list - 获取权限列表
- /api/system/permission/module/{module} - 按模块获取权限
- /api/system/permission/create - 创建权限
- /api/system/permission/update - 更新权限
- /api/system/permission/{id} - 删除权限
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional, List

from src.app.deps import get_db, get_current_user, CurrentUser, require_admin
from src.app.response import success_response, error_response
from src.services.rbac_service import RbacService

router = APIRouter(prefix="/api/system/permission", tags=["权限管理"])


# ========== 请求/响应模型 ==========

class PermissionCreate(BaseModel):
    """创建权限请求"""
    permissionCode: str
    permissionName: str
    module: str
    description: Optional[str] = None
    sortOrder: int = 0


class PermissionUpdate(BaseModel):
    """更新权限请求"""
    id: int
    permissionCode: Optional[str] = None
    permissionName: Optional[str] = None
    module: Optional[str] = None
    description: Optional[str] = None
    sortOrder: Optional[int] = None
    status: Optional[int] = None


# ========== 权限管理接口 ==========

@router.get("/list")
async def get_permission_list(
    _: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """获取所有权限列表"""
    try:
        permissions = await RbacService.get_all_permissions(db)
        return success_response([{
            "id": p.id,
            "permissionCode": p.permission_code,
            "permissionName": p.permission_name,
            "module": p.module,
            "description": p.description,
            "sortOrder": p.sort_order,
            "status": 1 if p.status else 0,
            "createdAt": str(p.created_at) if p.created_at else None,
            "updatedAt": str(p.updated_at) if p.updated_at else None,
        } for p in permissions])
    except Exception as e:
        return error_response(str(e))


@router.get("/module/{module}")
async def get_permissions_by_module(
    module: str,
    _: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """按模块获取权限"""
    try:
        permissions = await RbacService.get_permissions_by_module(db, module)
        return success_response([{
            "id": p.id,
            "permissionCode": p.permission_code,
            "permissionName": p.permission_name,
            "module": p.module,
            "description": p.description,
            "sortOrder": p.sort_order,
            "status": 1 if p.status else 0,
        } for p in permissions])
    except Exception as e:
        return error_response(str(e))


@router.post("/create")
async def create_permission(
    data: PermissionCreate,
    _: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """创建权限"""
    try:
        permission = await RbacService.create_permission(
            db=db,
            permission_code=data.permissionCode,
            permission_name=data.permissionName,
            module=data.module,
            description=data.description,
            sort_order=data.sortOrder,
        )
        return success_response({
            "id": permission.id,
            "permissionCode": permission.permission_code,
            "permissionName": permission.permission_name,
            "module": permission.module,
            "description": permission.description,
            "sortOrder": permission.sort_order,
            "status": 1 if permission.status else 0,
        }, msg="权限创建成功")
    except ValueError as e:
        return error_response(str(e), code=400)
    except Exception as e:
        return error_response(str(e))


@router.put("/update")
async def update_permission(
    data: PermissionUpdate,
    _: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """更新权限"""
    try:
        permission = await RbacService.update_permission(
            db=db,
            permission_id=data.id,
            permission_code=data.permissionCode,
            permission_name=data.permissionName,
            module=data.module,
            description=data.description,
            sort_order=data.sortOrder,
            status=bool(data.status) if data.status is not None else None,
        )
        if not permission:
            return error_response("权限不存在", code=404)
        return success_response(msg="权限更新成功")
    except Exception as e:
        return error_response(str(e))


@router.delete("/{permission_id}")
async def delete_permission(
    permission_id: int,
    _: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """删除权限"""
    try:
        result = await RbacService.delete_permission(db, permission_id)
        if not result:
            return error_response("权限不存在", code=404)
        return success_response(msg="权限删除成功")
    except Exception as e:
        return error_response(str(e))
