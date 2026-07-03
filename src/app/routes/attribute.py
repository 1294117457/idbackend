"""属性管理路由 - 兼容 idfrontend-admin"""
from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional, List

from src.app.deps import get_db
from src.app import response as R
from src.services.attribute_service import AttributeService

router = APIRouter(prefix="/api/rule-attribute", tags=["属性管理"])


class RuleAttributeRequest(BaseModel):
    attributeCode: str
    attributeType: str        # 'CONDITION' | 'TRANSFORM'
    attributeValue: str
    inputMax: Optional[float] = None
    inputMin: Optional[float] = None
    inputInterval: Optional[str] = None  # 'OPEN' | 'CLOSED' | 'LEFT_OPEN' | 'RIGHT_OPEN'
    displayOrder: int = 0
    description: Optional[str] = None
    isActive: Optional[bool] = True


def format_attr(attr) -> dict:
    """格式化属性响应"""
    return {
        "id": attr.id,
        "attributeCode": attr.attribute_code,
        "attributeType": attr.attribute_type,
        "attributeValue": attr.attribute_value,
        "inputMax": attr.input_max,
        "inputMin": attr.input_min,
        "inputInterval": attr.input_interval,
        "displayOrder": attr.display_order,
        "description": attr.description,
        "isActive": attr.is_active,
    }


@router.get("/list")
async def list_attributes(
    db: AsyncSession = Depends(get_db),
):
    """获取所有启用的属性"""
    attrs = await AttributeService.get_all_active(db)
    return R.success_resp([format_attr(a) for a in attrs])


@router.get("/list-by-type/{type}")
async def list_by_type(
    type: str = Path(..., description="属性类型 CONDITION/TRANSFORM"),
    db: AsyncSession = Depends(get_db),
):
    """根据类型获取属性"""
    attrs = await AttributeService.get_by_type(db, type)
    return R.success_resp([format_attr(a) for a in attrs])


@router.get("/list-by-code/{code}")
async def list_by_code(
    code: str = Path(..., description="属性编码"),
    db: AsyncSession = Depends(get_db),
):
    """根据编码获取属性"""
    attrs = await AttributeService.get_by_code(db, code)
    return R.success_resp([format_attr(a) for a in attrs])


@router.get("/{attribute_id}")
async def get_detail(
    attribute_id: int = Path(..., description="属性ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取属性详情"""
    attr = await AttributeService.get_by_id(db, attribute_id)
    if not attr:
        return R.not_found_resp("属性不存在")
    return R.success_resp(format_attr(attr))


@router.post("/create")
async def create(
    data: RuleAttributeRequest,
    db: AsyncSession = Depends(get_db),
):
    """创建属性"""
    try:
        attr = await AttributeService.create(
            db,
            attribute_code=data.attributeCode,
            attribute_type=data.attributeType,
            attribute_value=data.attributeValue,
            input_min=data.inputMin,
            input_max=data.inputMax,
            input_interval=data.inputInterval,
            display_order=data.displayOrder,
            description=data.description,
        )
        return R.created_resp({"id": attr.id})
    except ValueError as e:
        return R.bad_request_resp(str(e))


@router.put("/{attribute_id}")
async def update(
    attribute_id: int = Path(..., description="属性ID"),
    data: RuleAttributeRequest = ...,
    db: AsyncSession = Depends(get_db),
):
    """更新属性"""
    try:
        kwargs = {
            "attribute_code": data.attributeCode,
            "attribute_type": data.attributeType,
            "attribute_value": data.attributeValue,
            "input_min": data.inputMin,
            "input_max": data.inputMax,
            "input_interval": data.inputInterval,
            "display_order": data.displayOrder,
            "description": data.description,
            "is_active": data.isActive,
        }
        kwargs = {k: v for k, v in kwargs.items() if v is not None}

        attr = await AttributeService.update(db, attribute_id, **kwargs)
        if not attr:
            return R.not_found_resp("属性不存在")
        return R.success_resp({"id": attr.id})
    except ValueError as e:
        return R.bad_request_resp(str(e))


@router.delete("/{attribute_id}")
async def delete(
    attribute_id: int = Path(..., description="属性ID"),
    db: AsyncSession = Depends(get_db),
):
    """删除属性"""
    attr = await AttributeService.get_by_id(db, attribute_id)
    if not attr:
        return R.not_found_resp("属性不存在")

    await AttributeService.delete(db, attribute_id)
    return R.success_resp(msg="删除成功")
