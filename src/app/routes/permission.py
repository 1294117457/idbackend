"""权限管理 API

提供前端期望的 RBAC 权限管理接口：
- /api/system/permission/list - 获取权限列表
- /api/system/permission/create - 创建权限
- /api/system/permission/update - 更新权限
- /api/system/permission/{id} - 删除权限
- /api/system/permission/interfaces - 获取可绑定的接口列表
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional, List

from src.app.deps import get_db, CurrentUser, require_admin
from src.app.response import success_response, error_response
from src.services.rbac_service import RbacService

router = APIRouter(prefix="/api/system/permission", tags=["权限管理"])


# ========== 请求/响应模型 ==========

class PermissionCreate(BaseModel):
    """创建权限请求"""
    permissionCode: str
    permissionName: str
    apiPath: Optional[str] = None
    description: Optional[str] = None
    sortOrder: int = 0


class PermissionUpdate(BaseModel):
    """更新权限请求"""
    id: int
    permissionCode: Optional[str] = None
    permissionName: Optional[str] = None
    apiPath: Optional[str] = None
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
            "apiPath": p.api_path,
            "description": p.description,
            "sortOrder": p.sort_order,
            "status": 1 if p.status else 0,
            "createdAt": str(p.created_at) if p.created_at else None,
            "updatedAt": str(p.updated_at) if p.updated_at else None,
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
            code=data.permissionCode,
            name=data.permissionName,
            route_path=data.apiPath,
            description=data.description,
            sort_order=data.sortOrder,
        )
        return success_response({
            "id": permission.id,
            "permissionCode": permission.permission_code,
            "permissionName": permission.permission_name,
            "apiPath": permission.api_path,
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
            name=data.permissionName,
            route_path=data.apiPath,
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


# ========== 接口扫描 ==========

@router.get("/interfaces")
async def get_all_interfaces(
    _: CurrentUser = Depends(require_admin),
):
    """获取所有可用的 API 接口列表"""
    from src.main import app

    interfaces = []

    for route in app.routes:
        if hasattr(route, "path") and hasattr(route, "methods"):
            path = route.path

            # 只获取 /api 开头的接口
            if not path.startswith("/api"):
                continue

            for method in route.methods:
                if method in ("HEAD", "OPTIONS"):
                    continue

                # 生成权限编码
                perm_code = _extract_permission_code(path, method)
                interfaces.append({
                    "path": path,
                    "method": method,
                    "code": perm_code,
                    "label": f"[{method}] {path}",
                })

    # 去重并排序
    seen = set()
    unique_interfaces = []
    for iface in interfaces:
        key = f"{iface['method']}:{iface['path']}"
        if key not in seen:
            seen.add(key)
            unique_interfaces.append(iface)

    unique_interfaces.sort(key=lambda x: x['path'])
    return success_response(unique_interfaces)


def _extract_permission_code(path: str, method: str) -> str:
    """从路径提取权限代码"""
    path = path.lstrip("/")
    parts = path.split("/")

    resource = None
    action = None

    for i, part in enumerate(parts):
        if part in ("system", "api"):
            continue
        if part.startswith("{") or part.isdigit():
            continue

        resource = part
        if i == len(parts) - 1:
            action_map = {
                "GET": "read",
                "POST": "create",
                "PUT": "update",
                "PATCH": "update",
                "DELETE": "delete",
            }
            action = action_map.get(method, "manage")

    if resource and action:
        return f"{resource}:{action}"
    return f"{method.lower()}:unknown"


@router.post("/scan-interfaces")
async def scan_interfaces(
    _: CurrentUser = Depends(require_admin),
):
    """扫描并生成权限代码建议

    从路由中提取 resource:action 格式的权限代码
    """
    from src.main import app

    permissions = []
    seen = set()

    for route in app.routes:
        if hasattr(route, "path") and hasattr(route, "methods"):
            path = route.path

            if not path.startswith("/api"):
                continue

            for method in route.methods:
                if method in ("HEAD", "OPTIONS"):
                    continue

                perm_code = _extract_permission_code(path, method)
                if perm_code and perm_code not in seen:
                    seen.add(perm_code)
                    permissions.append({
                        "path": path,
                        "method": method,
                        "code": perm_code,
                    })

    return success_response({
        "permissions": permissions,
        "count": len(permissions),
    })
