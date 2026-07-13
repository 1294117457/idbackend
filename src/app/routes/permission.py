"""权限管理 API

提供前端期望的 RBAC 权限管理接口：
- /api/system/permission/list - 获取权限列表
- /api/system/permission/create - 创建权限
- /api/system/permission/update - 更新权限
- /api/system/permission/{id} - 删除权限
- /api/system/permission/interfaces - 获取可绑定的接口列表

架构约定（与 file/template_category 一致）：
- Request 直接喂给 service（service 内部用 req.to_orm / req.apply_to）
- 业务异常 → 由全局 exception_handlers 自动翻译为 HTTP 响应
- VO 由 schema.from_orm_to_vo 生成
"""

from fastapi import APIRouter, Depends, Path, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.deps import get_db
from src.app import response as R
from src.app.schemas.permission import (
    PermissionCreateRequest,
    PermissionUpdateRequest,
    PermissionVO,
    ApiInterfaceVO,
)
from src.app.schemas.errors import NotFoundError
from src.services.rbac_service import RbacService


router = APIRouter(prefix="/api/system/permission", tags=["权限管理"])


@router.get("/list")
async def get_permission_list(
    db: AsyncSession = Depends(get_db),
):
    """获取所有权限列表"""
    permissions = await RbacService.get_all_permissions(db)
    return R.query_resp(
        [PermissionVO.from_orm_to_vo(p).model_dump() for p in permissions]
    )


@router.post("/create", status_code=201)
async def create_permission(
    req: PermissionCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """创建权限"""
    permission = await RbacService.create_permission_from_request(db, req)
    return R.created_resp(
        PermissionVO.from_orm_to_vo(permission).model_dump(),
        msg="权限创建成功",
    )


@router.put("/update")
async def update_permission(
    req: PermissionUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """更新权限"""
    permission = await RbacService.update_permission_from_request(db, req)
    if not permission:
        raise NotFoundError(f"权限不存在: id={req.id}")
    return R.success_resp(msg="权限更新成功")


@router.delete("/{permission_id}")
async def delete_permission(
    permission_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db),
):
    """删除权限"""
    ok = await RbacService.delete_permission(db, permission_id)
    if not ok:
        raise NotFoundError(f"权限不存在: id={permission_id}")
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
                ApiInterfaceVO.from_route(path, method, perm_code).model_dump()
            )

    interfaces.sort(key=lambda x: x["path"])
    return R.query_resp(interfaces)
