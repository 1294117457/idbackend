"""Attribute 管理路由

接口约定：
- 前缀：/api/rule-attribute
- 路由层只做三件事：接 DTO → 调 service → 包 R 响应
- **零 try/except**：业务异常由全局 exception_handlers 自动翻译
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.app import response as R
from src.app.dependencies import get_db
from src.app.schemas.template import (
    AttributeCreateRequest,
    AttributeUpdateRequest,
    AttributeDeleteRequest,
    AttributeVO,
    AttributeListVO,
)
from src.services import AttributeService

router = APIRouter(prefix="/api/rule-attribute", tags=["属性管理"])


# ============================================================
# 读接口
# ============================================================

class AttributeListQueryRequest(BaseModel):
    """属性列表查询请求（GET /list）"""

    model_config = {"populate_by_name": True}

    type: str | None = Field(default=None, description="按类型过滤 CONDITION/TRANSFORM")
    groupCode: str | None = Field(default=None, description="按 group_code 过滤")
    isActive: bool | None = Field(default=True)
    pageNum: int = Field(default=1, ge=1)
    # 上限放至 500，给管理端 scoreAttribute.vue pageSize=200 留余量（一次拉所有 group）
    pageSize: int = Field(default=20, ge=1, le=500)


@router.get("/list")
async def list_attributes(
    type: str | None = Query(default=None, description="CONDITION/TRANSFORM"),
    groupCode: str | None = Query(default=None, description="group_code 过滤"),
    isActive: bool | None = Query(default=True),
    pageNum: int = Query(default=1, ge=1),
    pageSize: int = Query(default=20, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """分页列表（Page[AttributeVO]）"""
    type_upper = type.upper() if type else None
    attributes, total = await AttributeService.list_paged(
        db,
        is_active=isActive,
        attr_type=type_upper,
        group_code=groupCode,
        page_num=pageNum,
        page_size=pageSize,
    )
    vo = AttributeListVO.from_list_to_page(
        items=[AttributeVO.from_orm_to_vo(a) for a in attributes],
        total=total,
        page_num=pageNum,
        page_size=pageSize,
    )
    return R.query_resp(vo.model_dump())


@router.get("/detail")
async def get_attribute_detail(
    id: int = Query(..., ge=1),
    db: AsyncSession = Depends(get_db),
):
    """属性详情"""
    attribute = await AttributeService.get_by_id(db, id)
    return R.query_resp(AttributeVO.from_orm_to_vo(attribute).model_dump())


# ============================================================
# 写接口
# ============================================================

@router.post("", status_code=201)
async def create_attribute(
    req: AttributeCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """创建属性（service 内部校验 type / formula / group_name）"""
    attribute = await AttributeService.create(db, req)
    return R.created_resp(
        AttributeVO.from_orm_to_vo(attribute).model_dump(),
        msg="属性创建成功",
    )


@router.post("/update")
async def update_attribute(
    req: AttributeUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """修改属性（service 校验 type 变化时的 value / 区间）"""
    attribute = await AttributeService.update(db, req.id, req)
    return R.success_resp(
        AttributeVO.from_orm_to_vo(attribute).model_dump(),
        msg="更新成功",
    )


@router.post("/delete")
async def delete_attribute(
    req: AttributeDeleteRequest,
    db: AsyncSession = Depends(get_db),
):
    """删除属性（FK CASCADE 自动清理 rule_attribute 行，不影响 application 历史）"""
    await AttributeService.delete(db, req.id)
    return R.success_resp(msg="删除成功")