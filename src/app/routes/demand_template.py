"""需求模板路由 - 兼容前端"""
from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional, List

from src.app.deps import get_db
from src.app.context import get_username
from src.app import response as R
from src.services.demand_service import DemandTemplateService

router = APIRouter(prefix="/api/demand-template", tags=["需求模板"])


class DemandTemplateCreate(BaseModel):
    templateName: str
    conditions: Optional[List[str]] = []
    description: Optional[str] = None
    sortOrder: int = 0


class DemandTemplateUpdate(BaseModel):
    templateName: Optional[str] = None
    conditions: Optional[List[str]] = None
    description: Optional[str] = None
    sortOrder: Optional[int] = None
    isActive: Optional[bool] = None


@router.get("/active")
async def get_active(
    db: AsyncSession = Depends(get_db),
):
    """学生端 - 获取启用的模板"""
    templates = await DemandTemplateService.get_active(db)
    return R.success_resp([{
        "id": t.id,
        "templateName": t.template_name,
        "conditions": t.conditions,
        "description": t.description,
    } for t in templates])


@router.get("/list")
async def get_all(
    db: AsyncSession = Depends(get_db),
):
    """管理端 - 获取所有模板"""
    templates = await DemandTemplateService.get_all(db)
    return R.success_resp([{
        "id": t.id,
        "templateName": t.template_name,
        "conditions": t.conditions,
        "description": t.description,
        "sortOrder": t.sort_order,
        "isActive": t.is_active,
        "createdBy": t.created_by,
    } for t in templates])


@router.post("/create")
async def create(
    data: DemandTemplateCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建需求模板"""
    template = await DemandTemplateService.create(
        db,
        template_name=data.templateName,
        conditions=data.conditions,
        description=data.description,
        created_by=get_username(),
        sort_order=data.sortOrder,
    )
    return R.created_resp({"id": template.id})


@router.put("/{template_id}")
async def update(
    template_id: int = Path(..., description="模板ID"),
    data: DemandTemplateUpdate = ...,
    db: AsyncSession = Depends(get_db),
):
    """更新需求模板"""
    kwargs = {}
    if data.templateName is not None:
        kwargs["template_name"] = data.templateName
    if data.conditions is not None:
        kwargs["conditions"] = data.conditions
    if data.description is not None:
        kwargs["description"] = data.description
    if data.sortOrder is not None:
        kwargs["sort_order"] = data.sortOrder
    if data.isActive is not None:
        kwargs["is_active"] = data.isActive

    template = await DemandTemplateService.update(db, template_id, **kwargs)
    if not template:
        return R.not_found_resp("模板不存在")
    return R.success_resp({"id": template.id})


@router.delete("/{template_id}")
async def delete(
    template_id: int = Path(..., description="模板ID"),
    db: AsyncSession = Depends(get_db),
):
    """删除需求模板"""
    result = await DemandTemplateService.delete(db, template_id)
    if not result:
        return R.not_found_resp("模板不存在")
    return R.success_resp(msg="删除成功")
