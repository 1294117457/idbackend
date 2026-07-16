"""角色管理 API

架构约定（与 file/template_category 一致）：
- Request 直接喂给 service（service 内部用 req.to_orm / req.apply_to）
- 业务异常 → 由全局 exception_handlers 自动翻译为 HTTP 响应
- VO 由 schema.from_orm_to_vo 生成
"""
from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.dependencies import get_db
from src.app import response as R
from src.app.schemas.role import (
    RoleCreateRequest,
    RoleUpdateRequest,
    RolePermissionAssignRequest,
    RoleVO,
    RoleDetailVO,
    PermissionInRoleVO,
)
from src.app.schemas.errors import NotFoundError
from src.services.rbac_service import RbacService


router = APIRouter(prefix="/api/system/role", tags=["角色管理"])


@router.get("/list")
async def get_role_list(db: AsyncSession = Depends(get_db)):
    """获取所有角色列表"""
    roles = await RbacService.get_all_roles(db)
    return R.query_resp(
        [RoleVO.from_orm_to_vo(r).model_dump() for r in roles]
    )


@router.get("/{role_id}")
async def get_role_detail(
    role_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db),
):
    """获取角色详情"""
    role = await RbacService.get_role_by_id(db, role_id)
    if not role:
        raise NotFoundError(f"角色不存在: id={role_id}")
    permissions = await RbacService.get_role_permissions(db, role_id)
    return R.query_resp(RoleDetailVO.from_orm_to_vo(role, permissions).model_dump())


@router.post("/create", status_code=201)
async def create_role(
    req: RoleCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """创建角色（DTO 直接传给 service）"""
    role = await RbacService.create_role_from_request(db, req)
    return R.created_resp(
        RoleVO.from_orm_to_vo(role).model_dump(),
        msg="角色创建成功",
    )


@router.put("/update")
async def update_role(
    req: RoleUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """更新角色"""
    role = await RbacService.update_role_from_request(db, req)
    if not role:
        raise NotFoundError(f"角色不存在: id={req.id}")
    return R.success_resp(msg="角色更新成功")


@router.delete("/{role_id}")
async def delete_role(
    role_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db),
):
    """删除角色"""
    ok = await RbacService.delete_role(db, role_id)
    if not ok:
        raise NotFoundError(f"角色不存在: id={role_id}")
    return R.success_resp(msg="角色删除成功")


@router.get("/{role_id}/permissions")
async def get_role_permissions(
    role_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db),
):
    """获取角色的权限列表"""
    from src.app.schemas.permission import PermissionVO

    permissions = await RbacService.get_role_permissions(db, role_id)
    return R.query_resp(
        [PermissionInRoleVO.from_orm_to_vo(p).model_dump() for p in permissions]
    )


@router.post("/assignPermissions")
async def assign_permissions_to_role(
    req: RolePermissionAssignRequest,
    db: AsyncSession = Depends(get_db),
):
    """为角色分配权限"""
    await RbacService.assign_permissions_to_role_from_request(db, req)
    return R.success_resp(msg="权限分配成功")
