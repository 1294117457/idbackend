"""模板路由 - 兼容前端"""
from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete
from pydantic import BaseModel
from typing import Optional, List

from src.app.deps import get_db, get_current_user, CurrentUser
from src.app.response import success_response, error_response
from src.services import TemplateService
from src.services.attribute_service import AttributeService
from src.models import ScoreTemplate, ScoreTemplateRule, RuleAttributeMapping

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
    user: CurrentUser = Depends(get_current_user),
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


# ========== 模板更新/删除 ==========

class ScoringRuleRequest(BaseModel):
    id: Optional[int] = None
    ruleType: str
    ruleName: Optional[str] = None
    ruleScore: Optional[float] = None
    priority: int = 0
    description: Optional[str] = None
    attributeIds: Optional[List[int]] = None


class UpdateTemplateRequest(BaseModel):
    templateName: Optional[str] = None
    templateType: Optional[str] = None
    maxScore: Optional[float] = None
    scoreType: Optional[int] = None
    inputUnit: Optional[str] = None
    description: Optional[str] = None
    reviewCount: Optional[int] = None
    fieldId: Optional[int] = None
    rules: Optional[List[ScoringRuleRequest]] = None


@router.put("/{template_id}")
async def update_template(
    template_id: int = Path(..., description="模板ID"),
    request: UpdateTemplateRequest = ...,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新模板 (管理员)"""
    template = await TemplateService.get_template_by_id(db, template_id)
    if not template:
        return error_response("模板不存在", code=404)

    # 更新模板基本信息
    if request.templateName is not None:
        template.template_name = request.templateName
    if request.templateType is not None:
        template.template_type = request.templateType
    if request.maxScore is not None:
        template.template_max_score = request.maxScore
    if request.scoreType is not None:
        template.score_type = request.scoreType
    if request.inputUnit is not None:
        template.input_unit = request.inputUnit
    if request.description is not None:
        template.description = request.description
    if request.reviewCount is not None:
        template.review_count = request.reviewCount
    if request.fieldId is not None:
        template.field_id = request.fieldId

    # 重建规则
    if request.rules is not None:
        # 删除旧规则
        await db.execute(
            delete(RuleAttributeMapping).where(
                RuleAttributeMapping.rule_id.in_(
                    db.query(ScoreTemplateRule.id).filter(
                        ScoreTemplateRule.template_id == template_id
                    ).subquery()
                )
            )
        )
        await db.execute(
            delete(ScoreTemplateRule).where(ScoreTemplateRule.template_id == template_id)
        )

        # 创建新规则
        for rule_req in request.rules:
            rule = ScoreTemplateRule(
                template_id=template_id,
                rule_type=rule_req.ruleType,
                rule_name=rule_req.ruleName,
                rule_score=rule_req.ruleScore,
                priority=rule_req.priority,
                description=rule_req.description,
            )
            db.add(rule)
            await db.flush()

            # 绑定属性
            if rule_req.attributeIds:
                for idx, attr_id in enumerate(rule_req.attributeIds):
                    mapping = RuleAttributeMapping(
                        rule_id=rule.id,
                        attribute_id=attr_id,
                        is_required=True,
                        display_order=idx + 1,
                    )
                    db.add(mapping)

    await db.commit()
    return success_response({"id": template_id})


@router.delete("/{template_id}")
async def delete_template(
    template_id: int = Path(..., description="模板ID"),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除模板 (管理员)"""
    template = await TemplateService.get_template_by_id(db, template_id)
    if not template:
        return error_response("模板不存在", code=404)

    # 删除模板（规则会通过 CASCADE 自动删除）
    await db.delete(template)
    await db.commit()
    return success_response(msg="删除成功")
