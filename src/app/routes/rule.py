"""Rule 管理路由（v5 设计 - action-style 风格）

接口约定（与 template 一致）：
- 前缀：/api/rule
- 复合写操作走 /save /update /delete
- 单读操作保留 REST 风格（GET /list / GET /{id}）
- 零 try/except：业务异常由全局 exception_handlers 自动翻译

已废弃的旧接口（不再路由）：
- POST ""        → 用 POST /save
- PUT /{id}      → 用 POST /update
- DELETE /{id}   → 用 POST /delete
- POST /{id}/attributes   → 用 POST /update（内含 attributeIds）
- DELETE /{id}/attributes/{aid} → 同上
"""
from typing import Optional

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.deps import get_db
from src.app import response as R
from src.app.schemas.template import (
    RuleVO,
    RuleDetailVO,
    AttributeVO,
    RuleSaveRequest,
    RuleSaveUpdateRequest,
    RuleDeleteRequest,
)
from src.services import RuleService

router = APIRouter(prefix="/api/rule", tags=["规则"])


# ============================================================
# 读接口（保留 REST）
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
# v5 action-style 写接口
# ============================================================

@router.post("/save", status_code=201)
async def save_rule(
    req: RuleSaveRequest,
    db: AsyncSession = Depends(get_db),
):
    """新建 rule + 一次性绑 attribute（单事务）"""
    resp = await RuleService.save_rule(db, req)
    return R.created_resp(
        resp.model_dump(),
        msg="规则创建成功",
    )


@router.post("/update")
async def update_rule_with_attrs(
    req: RuleSaveUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """编辑 rule + 重置 attribute 绑定（DIFF，单事务）"""
    resp = await RuleService.update_rule(db, req)
    return R.success_resp(
        resp.model_dump(),
        msg="更新成功",
    )


@router.post("/delete")
async def delete_rule_by_id(
    req: RuleDeleteRequest,
    db: AsyncSession = Depends(get_db),
):
    """删除 rule（带被 template 引用检查）"""
    await RuleService.delete_rule_by_id(db, req)
    return R.success_resp(msg="删除成功")
