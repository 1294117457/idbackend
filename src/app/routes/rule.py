"""Rule 管理路由（v4 设计）

REST 接口约定（与 file.py 一致）：
- 前缀：/api/rule
- 路由层只做三件事：接 DTO → 调 service → 包 R 响应
- **零 try/except**：业务异常由全局 exception_handlers 自动翻译
"""
from typing import Optional

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.deps import get_db
from src.app import response as R
from src.app.schemas.template import (
    RuleCreateRequest,
    RuleUpdateRequest,
    RuleVO,
    RuleDetailVO,
    AttributeVO,
    RuleBindAttributeRequest,
)
from src.services import RuleService, AttributeService

router = APIRouter(prefix="/api/rule", tags=["规则"])


# ============================================================
# 读接口
# ============================================================

@router.get("/list")
async def list_rules(
    type: Optional[str] = Query(default=None, description="CONDITION/TRANSFORM"),
    isActive: Optional[bool] = Query(default=True),
    pageNum: int = Query(default=1, ge=1),
    pageSize: int = Query(default=20, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """分页列表"""
    rules, total = await RuleService.list_paged(
        db,
        is_active=isActive,
        rule_type=type.upper() if type else None,
        page_num=pageNum,
        page_size=pageSize,
    )
    from src.app.schemas.page import Page

    vo = Page[RuleVO].from_list_to_page(
        items=[RuleVO.from_orm_to_vo(r) for r in rules],
        total=total,
        page_num=pageNum,
        page_size=pageSize,
    )
    return R.query_resp(vo.model_dump())


@router.get("/{rule_id}")
async def get_rule_detail(
    rule_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db),
):
    """规则详情（含 attribute 列表）"""
    rule = await RuleService.get_with_attributes(db, rule_id)
    attr_vos = [
        AttributeVO.from_orm_to_vo(a)
        for a in sorted(rule.attributes, key=lambda a: a.sort_order)
    ]
    vo = RuleDetailVO.from_orm_to_vo(rule, attr_vos)
    return R.query_resp(vo.model_dump())


# ============================================================
# 写接口
# ============================================================

@router.post("", status_code=201)
async def create_rule(
    req: RuleCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """创建规则（service 校验 type-score 一致性）"""
    rule = await RuleService.create(db, req)
    return R.created_resp(
        RuleVO.from_orm_to_vo(rule).model_dump(),
        msg="规则创建成功",
    )


@router.put("/{rule_id}")
async def update_rule(
    rule_id: int = Path(..., ge=1),
    req: RuleUpdateRequest = ...,
    db: AsyncSession = Depends(get_db),
):
    """修改规则（service 校验 type-score 一致性）"""
    rule = await RuleService.update(db, rule_id, req)
    return R.success_resp(
        RuleVO.from_orm_to_vo(rule).model_dump(),
        msg="更新成功",
    )


@router.delete("/{rule_id}")
async def delete_rule(
    rule_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db),
):
    """删除规则（FK CASCADE 自动清理 template_rule / rule_attribute 行）"""
    await RuleService.delete(db, rule_id)
    return R.success_resp(msg="删除成功")


# ============================================================
# 关联操作
# ============================================================

@router.post("/{rule_id}/attributes", status_code=200)
async def bind_attribute(
    rule_id: int = Path(..., ge=1),
    req: RuleBindAttributeRequest = ...,
    db: AsyncSession = Depends(get_db),
):
    """rule 绑 attribute（v4 唯一硬校验：rule.type == attribute.type）

    失败抛 BadRequestError，错误信息明确指出 type 不一致。
    """
    await RuleService.bind_attribute(db, rule_id, req.attributeId)
    return R.success_resp(msg="绑定成功")


@router.delete("/{rule_id}/attributes/{attribute_id}")
async def unbind_attribute(
    rule_id: int = Path(..., ge=1),
    attribute_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db),
):
    """rule 解绑 attribute"""
    await RuleService.unbind_attribute(db, rule_id, attribute_id)
    return R.success_resp(msg="解绑成功")