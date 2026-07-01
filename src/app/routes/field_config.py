"""字段配置路由"""
from fastapi import APIRouter, Depends, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from pydantic import BaseModel
import json

from src.app.deps import get_db, get_current_user, CurrentUser
from src.app.response import success_response, error_response
from src.services.template_service import TemplateService

router = APIRouter(prefix="/api/field-config", tags=["字段配置"])


class FieldConfigCreate(BaseModel):
    field_key: str
    display_name: str
    field_type: str
    max_score: Optional[float] = None
    conditions: Optional[str] = None  # JSON string, not list
    description: Optional[str] = None
    college_code: Optional[str] = None
    academic_year: Optional[int] = None
    sort_order: int = 0


class FieldConfigUpdate(BaseModel):
    field_key: Optional[str] = None
    display_name: Optional[str] = None
    field_type: Optional[str] = None
    max_score: Optional[float] = None
    conditions: Optional[str] = None  # JSON string, not list
    description: Optional[str] = None
    college_code: Optional[str] = None
    academic_year: Optional[int] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class SubcategoryCreate(BaseModel):
    field_id: int
    sub_key: str
    display_name: str
    max_score: float
    description: Optional[str] = None
    sort_order: int = 0


class SubcategoryUpdate(BaseModel):
    sub_key: Optional[str] = None
    display_name: Optional[str] = None
    max_score: Optional[float] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


# ========== FieldConfig CRUD ==========

@router.get("/list")
async def get_field_config_list(
    type: Optional[str] = Query(None, description="字段类型: SCORE/DEMAND"),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取字段配置列表"""
    configs = await TemplateService.get_field_configs(db, field_type=type)
    return success_response([
        {
            "id": c.id,
            "fieldKey": c.field_key,
            "displayName": c.display_name,
            "fieldType": c.field_type,
            "maxScore": c.max_score,
            # 转换为 JSON string 供前端使用
            "conditions": json.dumps(c.conditions) if c.conditions else "[]",
            "description": c.description,
            "collegeCode": c.college_code,
            "academicYear": c.academic_year,
            "sortOrder": c.sort_order,
            "isActive": c.is_active,
        }
        for c in configs
    ])


@router.get("/list/all")
async def get_all_field_configs(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取所有字段配置"""
    configs = await TemplateService.get_field_configs(db)
    return success_response([
        {
            "id": c.id,
            "fieldKey": c.field_key,
            "displayName": c.display_name,
            "fieldType": c.field_type,
            "maxScore": c.max_score,
            "conditions": json.dumps(c.conditions) if c.conditions else "[]",
            "description": c.description,
            "collegeCode": c.college_code,
            "academicYear": c.academic_year,
            "sortOrder": c.sort_order,
            "isActive": c.is_active,
        }
        for c in configs
    ])


@router.get("/{config_id}")
async def get_field_config_by_id(
    config_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取字段配置详情"""
    config = await TemplateService.get_field_config_by_id(db, config_id)
    if not config:
        return error_response("字段配置不存在", code=404)

    return success_response({
        "id": config.id,
        "fieldKey": config.field_key,
        "displayName": config.display_name,
        "fieldType": config.field_type,
        "maxScore": config.max_score,
        "conditions": config.conditions,
        "description": config.description,
        "collegeCode": config.college_code,
        "academicYear": config.academic_year,
        "sortOrder": config.sort_order,
        "isActive": config.is_active,
    })


@router.post("")
async def create_field_config(
    data: FieldConfigCreate,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """创建字段配置"""
    # 转换 conditions: 如果是列表则转为 JSON string
    conditions = data.conditions
    if conditions and isinstance(conditions, list):
        conditions = json.dumps(conditions)

    config = await TemplateService.create_field_config(
        db=db,
        field_key=data.field_key,
        display_name=data.display_name,
        field_type=data.field_type,
        max_score=data.max_score,
        conditions=conditions,
        description=data.description,
        college_code=data.college_code,
        academic_year=data.academic_year,
        sort_order=data.sort_order,
        created_by=str(user.user_id),
    )
    return success_response({
        "id": config.id,
        "fieldKey": config.field_key,
        "displayName": config.display_name,
    })


@router.put("/{config_id}")
async def update_field_config(
    config_id: int,
    data: FieldConfigUpdate,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新字段配置"""
    config = await TemplateService.update_field_config(
        db=db,
        config_id=config_id,
        **data.model_dump(exclude_none=True),
    )
    if not config:
        return error_response("字段配置不存在", code=404)

    return success_response({
        "id": config.id,
        "fieldKey": config.field_key,
        "displayName": config.display_name,
    })


@router.delete("/{config_id}")
async def delete_field_config(
    config_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除字段配置"""
    result = await TemplateService.delete_field_config(db, config_id)
    if not result:
        return error_response("字段配置不存在", code=404)

    return success_response(msg="删除成功")


# ========== FieldSubcategory CRUD ==========

@router.get("/subcategory/list")
async def get_subcategory_list(
    fieldId: Optional[int] = Query(None, description="字段ID"),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取字段细分列表"""
    subcategories = await TemplateService.get_subcategories(db, field_id=fieldId)
    return success_response([
        {
            "id": s.id,
            "fieldId": s.field_id,
            "subKey": s.sub_key,
            "displayName": s.display_name,
            "maxScore": s.max_score,
            "description": s.description,
            "sortOrder": s.sort_order,
            "isActive": s.is_active,
        }
        for s in subcategories
    ])


@router.post("/subcategory")
async def create_subcategory(
    data: SubcategoryCreate,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """创建字段细分"""
    subcategory = await TemplateService.create_subcategory(
        db=db,
        field_id=data.field_id,
        sub_key=data.sub_key,
        display_name=data.display_name,
        max_score=data.max_score,
        description=data.description,
        sort_order=data.sort_order,
    )
    return success_response({
        "id": subcategory.id,
        "fieldId": subcategory.field_id,
        "subKey": subcategory.sub_key,
        "displayName": subcategory.display_name,
    })


@router.put("/subcategory/{subcategory_id}")
async def update_subcategory(
    subcategory_id: int,
    data: SubcategoryUpdate,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新字段细分"""
    subcategory = await TemplateService.update_subcategory(
        db=db,
        subcategory_id=subcategory_id,
        **data.model_dump(exclude_none=True),
    )
    if not subcategory:
        return error_response("字段细分不存在", code=404)

    return success_response({
        "id": subcategory.id,
        "subKey": subcategory.sub_key,
        "displayName": subcategory.display_name,
    })


@router.delete("/subcategory/{subcategory_id}")
async def delete_subcategory(
    subcategory_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除字段细分"""
    result = await TemplateService.delete_subcategory(db, subcategory_id)
    if not result:
        return error_response("字段细分不存在", code=404)

    return success_response(msg="删除成功")
