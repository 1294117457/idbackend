"""学生扩展字段管理路由

接口约定：
- 前缀：/api/extra-info-field
- 鉴权：PermissionMiddleware 已按权限码校验
- 路由层只做三件事：接 DTO → 调 service → 包 R 响应
- 零 try/except：业务异常由全局 exception_handlers 自动翻译

权限码（init_rbac_data.py 中注册）：
  extra_info:list    - GET /list, /active
  extra_info:detail  - GET /detail
  extra_info:create  - POST (create)
  extra_info:update  - POST /update
  extra_info:delete  - POST /delete
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.dependencies import get_db
from src.app import response as R
from src.app.schemas.extra_info_field import (
    ExtraInfoFieldCreateRequest,
    ExtraInfoFieldUpdateRequest,
    ExtraInfoFieldDeleteRequest,
    ExtraInfoFieldPageQueryRequest,
    ExtraInfoFieldVO,
)
from src.services.extra_info_field_service import ExtraInfoFieldService


router = APIRouter(prefix="/api/extra-info-field", tags=["学生扩展字段管理"])


# ============ 读接口 ============

@router.get("/list")
async def list_fields(
    req: Annotated[ExtraInfoFieldPageQueryRequest, Query()],
    db: AsyncSession = Depends(get_db),
):
    """分页列表（Page[ExtraInfoFieldVO]）"""
    page = await ExtraInfoFieldService.page(db, req)
    return R.query_resp(page.model_dump())


@router.get("/active")
async def get_active_fields(
    db: AsyncSession = Depends(get_db),
):
    """获取所有已启用的字段（供学生端展示/编辑使用）"""
    fields = await ExtraInfoFieldService.list_all(db, include_inactive=False)
    return R.query_resp([
        ExtraInfoFieldVO.from_orm_to_vo(f).model_dump() for f in fields
    ])


@router.get("/detail")
async def get_field_detail(
    id: int = Query(..., ge=1),
    db: AsyncSession = Depends(get_db),
):
    """字段详情"""
    field = await ExtraInfoFieldService.get_by_id(db, id)
    return R.query_resp(ExtraInfoFieldVO.from_orm_to_vo(field).model_dump())


# ============ 写接口 ============

@router.post("", status_code=201)
async def create_field(
    req: ExtraInfoFieldCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """创建字段"""
    field = await ExtraInfoFieldService.create(db, req)
    return R.created_resp(
        ExtraInfoFieldVO.from_orm_to_vo(field).model_dump(),
        msg="字段创建成功",
    )


@router.post("/update")
async def update_field(
    req: ExtraInfoFieldUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """修改字段"""
    field = await ExtraInfoFieldService.update(db, req.id, req)
    return R.success_resp(
        ExtraInfoFieldVO.from_orm_to_vo(field).model_dump(),
        msg="更新成功",
    )


@router.post("/delete")
async def delete_field(
    req: ExtraInfoFieldDeleteRequest,
    db: AsyncSession = Depends(get_db),
):
    """删除字段"""
    await ExtraInfoFieldService.delete(db, req.id)
    return R.success_resp(msg="删除成功")
