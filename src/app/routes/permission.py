"""权限管理 API

提供前端期望的 RBAC 权限管理接口：
- /api/system/permission/list - 获取权限列表
- /api/system/permission/create - 创建权限
- /api/system/permission/update - 更新权限
- /api/system/permission/{id} - 删除权限
- /api/system/permission/interfaces - 获取可绑定的接口列表
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional, List

from src.app.deps import get_db
from src.app import response as R
from src.services.rbac_service import RbacService

router = APIRouter(prefix="/api/system/permission", tags=["权限管理"])


# ========== 请求/响应模型 ==========


class PermissionCreate(BaseModel):
    """创建权限请求"""

    permissionCode: str
    permissionName: str
    module: Optional[str] = None
    apiPath: Optional[str] = None
    description: Optional[str] = None
    sortOrder: int = 0


class PermissionUpdate(BaseModel):
    """更新权限请求"""

    id: int
    permissionCode: Optional[str] = None
    permissionName: Optional[str] = None
    module: Optional[str] = None
    apiPath: Optional[str] = None
    description: Optional[str] = None
    sortOrder: Optional[int] = None
    status: Optional[int] = None


def _derive_module(permission_code: str) -> str:
    """从权限编码推导模块名（module:action → module）"""
    if ":" in permission_code:
        return permission_code.split(":")[0]
    return ""


# ========== 权限管理接口 ==========


@router.get("/list")
async def get_permission_list(
    db: AsyncSession = Depends(get_db),
):
    """获取所有权限列表"""
    permissions = await RbacService.get_all_permissions(db)
    return R.success_resp(
        [
            {
                "id": p.id,
                "permissionCode": p.permission_code,
                "permissionName": p.permission_name,
                "module": _derive_module(p.permission_code),
                "apiPath": p.api_path,
                "description": p.description,
                "sortOrder": p.sort_order,
                "status": 1 if p.status else 0,
                "createdAt": str(p.created_at) if p.created_at else None,
                "updatedAt": str(p.updated_at) if p.updated_at else None,
            }
            for p in permissions
        ]
    )


@router.post("/create")
async def create_permission(
    data: PermissionCreate,
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
        return R.created_resp(
            {
                "id": permission.id,
                "permissionCode": permission.permission_code,
                "permissionName": permission.permission_name,
                "module": _derive_module(permission.permission_code),
                "apiPath": permission.api_path,
                "description": permission.description,
                "sortOrder": permission.sort_order,
                "status": 1 if permission.status else 0,
            },
            msg="权限创建成功",
        )
    except ValueError as e:
        return R.bad_request_resp(str(e))


@router.put("/update")
async def update_permission(
    data: PermissionUpdate,
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
            return R.not_found_resp("权限不存在")
        return R.success_resp(msg="权限更新成功")
    except ValueError as e:
        return R.bad_request_resp(str(e))


@router.delete("/{permission_id}")
async def delete_permission(
    permission_id: int,
    db: AsyncSession = Depends(get_db),
):
    """删除权限"""
    result = await RbacService.delete_permission(db, permission_id)
    if not result:
        return R.not_found_resp("权限不存在")
    return R.success_resp(msg="权限删除成功")


# ========== 接口扫描 ==========


def _iter_routes(router):
    """递归遍历 FastAPI/Starlette 路由树，返回所有叶子 Route 对象。

    app.routes 顶层装的是 _IncludedRouter 包装对象，真实路由在
    original_router.routes 里，需要递归展开。
    """
    for route in router.routes:
        if type(route).__name__ == "_IncludedRouter":
            yield from _iter_routes(route.original_router)
        elif hasattr(route, "path") and hasattr(route, "methods"):
            yield route


@router.get("/interfaces")
async def get_all_interfaces(request: Request):
    """获取所有可用的 API 接口列表"""
    interfaces = []
    seen = set()

    for route in _iter_routes(request.app.router):
        path = route.path
        if not path.startswith("/api"):
            continue

        for method in route.methods or set():
            if method in ("HEAD", "OPTIONS"):
                continue
            key = f"{method}:{path}"
            if key in seen:
                continue
            seen.add(key)
            perm_code = _extract_permission_code(path, method)
            interfaces.append(
                {
                    "path": path,
                    "method": method,
                    "code": perm_code,
                    "label": f"[{method}] {path}",
                }
            )

    interfaces.sort(key=lambda x: x["path"])
    return R.success_resp(interfaces)


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
