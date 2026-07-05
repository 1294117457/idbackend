"""模板分类管理路由（Layer 1）

REST 接口约定：
- 前缀：/api/template-category
- 鉴权：PermissionMiddleware 已在中间件层通过 RbacService.get_path_permission 校验权限码
- 路由层只做参数解析 + 调用 service + 异常翻译，业务逻辑全部在 service

权限码（在 seed_permissions.py 中注册）：
  template_category:read    - GET 全部接口
  template_category:create  - POST
  template_category:update  - PUT
  template_category:delete  - DELETE
"""
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, Field, condecimal
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.deps import get_db
from src.app import response as R
from src.services.template_category_service import (
    TemplateCategoryService,
    CategoryNotFound,
    CategoryNameDuplicate,
    ParentAlreadyBound,
    CategoryHasActiveApplications,
    CategoryError,
)


router = APIRouter(prefix="/api/template-category", tags=["模板分类管理"])


# ===================== Request Schema =====================

class TemplateCategoryCreate(BaseModel):
    """创建分类请求体"""
    parentId: Optional[int] = Field(
        None, description="父分类 ID，null=创建根节点"
    )
    name: str = Field(..., min_length=1, max_length=100)
    maxScore: condecimal(ge=0, max_digits=5, decimal_places=2) = Field(
        ..., description="本级分数上限，不允许为 null"
    )
    sortOrder: int = Field(0, ge=0, description="同级展示顺序")
    description: Optional[str] = Field(None, max_length=255)


class TemplateCategoryUpdate(BaseModel):
    """修改分类请求体（所有字段可选）"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    maxScore: Optional[condecimal(ge=0, max_digits=5, decimal_places=2)] = None
    sortOrder: Optional[int] = Field(None, ge=0)
    isActive: Optional[bool] = None
    description: Optional[str] = Field(None, max_length=255)

    class Config:
        extra = "forbid"  # 禁止 parentId/isBindTemplate 等被传入


# ===================== Response 序列化 =====================

def _to_dict(category) -> dict:
    """ORM → API 响应格式（与 service 内 _serialize 保持一致）。"""
    return {
        "id": category.id,
        "name": category.name,
        "parentId": category.parent_id,
        "maxScore": str(category.max_score),
        "isBindTemplate": category.is_bind_template,
        "sortOrder": category.sort_order,
        "isActive": category.is_active,
        "description": category.description,
    }


def _to_detail_dict(category, path: list) -> dict:
    """详情用：附加完整路径信息。"""
    base = _to_dict(category)
    base["path"] = [
        {"id": p.id, "name": p.name} for p in path
    ]
    return base


# ===================== 读接口 =====================

@router.get("/tree")
async def get_category_tree(
    includeInactive: bool = Query(False, description="是否包含已停用节点"),
    db: AsyncSession = Depends(get_db),
):
    """获取完整分类树（嵌套结构）。"""
    tree = await TemplateCategoryService.get_tree(db, include_inactive=includeInactive)
    return R.success_resp(tree)


@router.get("/leaf")
async def get_leaf_categories(
    includeInactive: bool = Query(False, description="是否包含已停用节点"),
    db: AsyncSession = Depends(get_db),
):
    """获取所有叶子分类（供 Template 绑定时使用）。"""
    leaves = await TemplateCategoryService.get_leaf_categories(
        db, include_inactive=includeInactive
    )
    return R.success_resp([_to_dict(c) for c in leaves])


@router.get("/{category_id}")
async def get_category_detail(
    category_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db),
):
    """获取分类详情（含完整路径）。"""
    category = await TemplateCategoryService.get_by_id(db, category_id)
    if category is None:
        return R.not_found_resp("分类不存在")

    path = await TemplateCategoryService.get_category_path(db, category_id)
    return R.success_resp(_to_detail_dict(category, path))


@router.get("/{category_id}/delete-preview")
async def get_delete_preview(
    category_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db),
):
    """删除预览：返回将级联删除的内容清单，供前端强提醒对话窗渲染。"""
    try:
        preview = await TemplateCategoryService.get_delete_preview(db, category_id)
        return R.success_resp(preview)
    except CategoryNotFound as e:
        return R.not_found_resp(str(e))


# ===================== 写接口 =====================

@router.post("")
async def create_category(
    data: TemplateCategoryCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建分类（根或子分类）。"""
    try:
        if data.parentId is None:
            category = await TemplateCategoryService.create_root(
                db,
                name=data.name,
                max_score=Decimal(str(data.maxScore)),
                description=data.description,
                sort_order=data.sortOrder,
            )
        else:
            category = await TemplateCategoryService.create_child(
                db,
                parent_id=data.parentId,
                name=data.name,
                max_score=Decimal(str(data.maxScore)),
                description=data.description,
                sort_order=data.sortOrder,
            )
        return R.created_resp(_to_dict(category), msg="分类创建成功")
    except CategoryNameDuplicate as e:
        return R.bad_request_resp(str(e))
    except ParentAlreadyBound as e:
        return R.bad_request_resp(str(e))
    except CategoryNotFound as e:
        return R.not_found_resp(str(e))
    except CategoryError as e:
        return R.bad_request_resp(str(e))


@router.put("/{category_id}")
async def update_category(
    category_id: int = Path(..., ge=1),
    data: TemplateCategoryUpdate = ...,
    db: AsyncSession = Depends(get_db),
):
    """修改分类（仅允许 name/maxScore/sortOrder/isActive/description）。"""
    try:
        category = await TemplateCategoryService.update(
            db,
            category_id,
            name=data.name,
            max_score=Decimal(str(data.maxScore)) if data.maxScore is not None else None,
            sort_order=data.sortOrder,
            is_active=data.isActive,
            description=data.description,
        )
        return R.success_resp(_to_dict(category), msg="更新成功")
    except CategoryNotFound as e:
        return R.not_found_resp(str(e))
    except CategoryNameDuplicate as e:
        return R.bad_request_resp(str(e))
    except CategoryError as e:
        return R.bad_request_resp(str(e))


@router.delete("/{category_id}")
async def delete_category(
    category_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db),
):
    """删除分类（级联删除子分类与绑定的 template）。"""
    try:
        deleted_count = await TemplateCategoryService.delete(db, category_id)
        return R.success_resp(
            {"deletedCount": deleted_count},
            msg=f"成功删除 {deleted_count} 个分类节点（含级联）",
        )
    except CategoryNotFound as e:
        return R.not_found_resp(str(e))
    except CategoryHasActiveApplications as e:
        return R.bad_request_resp(
            f"该分类及其子分类下还有 {e.count} 条未关闭的申请，禁止删除",
            data={"activeApplicationCount": e.count},
        )
    except CategoryError as e:
        return R.bad_request_resp(str(e))