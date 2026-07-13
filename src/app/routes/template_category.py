"""模板分类管理路由（Layer 1）

REST 接口约定：
- 前缀：/api/template-category
- 鉴权：PermissionMiddleware 已按权限码校验
- 路由层只做三件事：接 DTO → 调 service → 包 R 响应。
  **零 try/except**：业务异常由全局 exception_handlers 自动翻译。
- DTO ↔ ORM 转换由 schema 完成，service 拿到的就是 ORM

权限码（seed_permissions.py 中注册）：
  template_category:read    - GET 全部接口
  template_category:create  - POST
  template_category:update  - PUT
  template_category:delete  - DELETE
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.deps import get_db
from src.app import response as R
from src.app.schemas.template_category import (
    TemplateCategoryCreateRequest,
    TemplateCategoryUpdateRequest,
    TemplateCategoryListQueryRequest,
    TemplateCategoryPageQueryRequest,
    TemplateCategoryVO,
    TemplateCategoryDetailVO,
    TemplateCategoryDeletePreviewVO,
)
from src.services.template_category_service import TemplateCategoryService


router = APIRouter(prefix="/api/template-category", tags=["模板分类管理"])


# ============ 读接口 ============

@router.get("/list")
async def list_categories(
    req: Annotated[TemplateCategoryPageQueryRequest, Query()],
    db: AsyncSession = Depends(get_db),
):
    """平铺分页列表（Page[TemplateCategoryVO]）。

    前端拿到 resp.data.list 后按 parentId 自组树，无后端嵌套。
    """
    page = await TemplateCategoryService.page(db, req)
    return R.query_resp(page.model_dump())


@router.get("/leaf")
async def get_leaf_categories(
    req: Annotated[TemplateCategoryListQueryRequest, Query()],
    db: AsyncSession = Depends(get_db),
):
    """所有可绑 template 的分类（is_bind_template=FALSE）。"""
    leaves = await TemplateCategoryService.get_leaf_categories(
        db, include_inactive=req.includeInactive
    )
    return R.query_resp(
        [TemplateCategoryVO.from_orm_to_vo(c).model_dump() for c in leaves]
    )


@router.get("/{category_id}")
async def get_category_detail(
    category_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db),
):
    """分类详情（含完整路径）。"""
    category = await TemplateCategoryService.get_by_id(db, category_id)
    path = await TemplateCategoryService.get_category_path(db, category_id)
    vo = TemplateCategoryDetailVO.from_orm_to_vo(category, path)
    return R.query_resp(vo.model_dump())


@router.get("/{category_id}/delete-preview")
async def get_delete_preview(
    category_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db),
):
    """删除预览（强提醒对话窗数据源）。"""
    payload = await TemplateCategoryService.get_delete_preview(db, category_id)
    vo = TemplateCategoryDeletePreviewVO.from_service_payload(payload)
    return R.query_resp(vo.model_dump())


# ============ 写接口 ============

@router.post("", status_code=201)
async def create_category(
    req: TemplateCategoryCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """创建分类（根或子）。DTO 直接传给 service，无需展开字段。"""
    category = await TemplateCategoryService.create(db, req)
    return R.created_resp(
        TemplateCategoryVO.from_orm_to_vo(category).model_dump(),
        msg="分类创建成功",
    )


@router.put("/{category_id}")
async def update_category(
    category_id: int = Path(..., ge=1),
    req: TemplateCategoryUpdateRequest = ...,
    db: AsyncSession = Depends(get_db),
):
    """修改分类。DTO 整体交给 service：apply_to() 处理非空字段。"""
    category = await TemplateCategoryService.update(db, category_id, req)
    return R.success_resp(
        TemplateCategoryVO.from_orm_to_vo(category).model_dump(),
        msg="更新成功",
    )


@router.delete("/{category_id}")
async def delete_category(
    category_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db),
):
    """删除分类（级联）。"""
    deleted_count = await TemplateCategoryService.delete(db, category_id)
    return R.success_resp(
        {"deletedCount": deleted_count},
        msg=f"成功删除 {deleted_count} 个分类节点（含级联）",
    )
