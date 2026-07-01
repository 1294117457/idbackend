"""模板路由 - 兼容前端"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional

from src.app.deps import get_db, get_current_user, CurrentUser, require_admin
from src.app.response import success_response, error_response
from src.services import TemplateService

router = APIRouter(prefix="/api/bonus-template", tags=["模板"])


@router.get("/list")
async def list_templates(
    _: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取模板列表"""
    templates = await TemplateService.get_templates(db)
    return success_response([{
        "id": t.id,
        "templateName": t.template_name,
        "templateType": t.template_type,
        "scoreType": t.score_type,
        "maxScore": t.template_max_score,
        "inputUnit": t.input_unit,
        "description": t.description,
    } for t in templates])


@router.get("/{template_id}")
async def get_template(
    template_id: int,
    _: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取模板详情"""
    template = await TemplateService.get_template_by_id(db, template_id)
    if not template:
        return error_response("模板不存在", code=404)

    # 获取规则
    rules = await TemplateService.get_template_rules(db, template_id)

    return success_response({
        "id": template.id,
        "templateName": template.template_name,
        "templateType": template.template_type,
        "scoreType": template.score_type,
        "maxScore": template.template_max_score,
        "inputUnit": template.input_unit,
        "description": template.description,
        "rules": [{
            "id": r.id,
            "ruleName": r.rule_name,
            "ruleType": r.rule_type,
            "ruleScore": r.rule_score,
        } for r in rules],
    })


# ========== 管理员接口 ==========

class CreateTemplateRequest(BaseModel):
    templateName: str
    templateType: str = "CONDITION"
    maxScore: float
    scoreType: int = 0
    inputUnit: str = ""
    description: str = ""
    reviewCount: int = 1


@router.post("/create")
async def create_template(
    request: CreateTemplateRequest,
    user: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """创建模板 (管理员)"""
    template = await TemplateService.create_template(
        db,
        template_name=request.templateName,
        template_type=request.templateType,
        template_max_score=request.maxScore,
        score_type=request.scoreType,
        input_unit=request.inputUnit,
        description=request.description,
        created_by=user.username,
        review_count=request.reviewCount,
    )
    return success_response({
        "id": template.id,
        "templateName": template.template_name,
    })
