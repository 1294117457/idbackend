"""Agent 工具 - 直接调用 Service 层"""
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession

from services import UserService, TemplateService, ApplicationService


async def get_user_info_tool(
    db: AsyncSession,
    user_id: int,
) -> dict:
    """获取用户信息"""
    user = await UserService.get_user_by_id(db, user_id)
    if not user:
        return {"error": "用户不存在"}

    return {
        "userId": user.id,
        "username": user.username,
        "fullName": user.full_name,
        "studentId": user.student_id,
        "major": user.major,
        "isConfirmed": user.is_confirmed,
        "academicScore": user.academic_score,
        "specialtyScore": user.specialty_score,
        "comprehensiveScore": user.comprehensive_score,
    }


async def get_user_scores_tool(
    db: AsyncSession,
    user_id: int,
) -> dict:
    """获取用户积分"""
    return await UserService.get_user_scores(db, user_id)


async def get_templates_tool(
    db: AsyncSession,
    score_type: Optional[int] = None,
) -> List[dict]:
    """获取加分模板列表"""
    templates = await TemplateService.get_templates(db, score_type)
    return [
        {
            "id": t.id,
            "name": t.template_name,
            "type": t.template_type,
            "maxScore": t.template_max_score,
            "inputUnit": t.input_unit,
        }
        for t in templates
    ]


async def get_template_rules_tool(
    db: AsyncSession,
    template_id: int,
) -> List[dict]:
    """获取模板规则"""
    rules = await TemplateService.get_template_rules(db, template_id)
    return [
        {
            "id": r.id,
            "name": r.rule_name,
            "score": r.rule_score,
            "type": r.rule_type,
        }
        for r in rules
    ]


async def create_application_tool(
    db: AsyncSession,
    user_id: int,
    template_id: int,
    rule_id: Optional[int] = None,
    apply_input: Optional[float] = None,
    proof_file_ids: Optional[List[int]] = None,
) -> dict:
    """创建申请"""
    template = await TemplateService.get_template_by_id(db, template_id)
    if not template:
        return {"error": "模板不存在"}

    apply_score = float(template.template_max_score)

    application = await ApplicationService.create_application(
        db,
        user_id=user_id,
        template_id=template_id,
        template_name=template.template_name,
        apply_score=apply_score,
        rule_id=rule_id,
        apply_input=apply_input,
    )

    if proof_file_ids:
        for file_id in proof_file_ids:
            await ApplicationService.add_proof(db, application.id, file_id)

    return {
        "applicationId": application.id,
        "status": application.status,
        "applyScore": application.apply_score,
    }


async def get_user_applications_tool(
    db: AsyncSession,
    user_id: int,
    status: Optional[int] = None,
) -> List[dict]:
    """获取用户申请列表"""
    applications, _ = await ApplicationService.get_user_applications(
        db, user_id, status
    )
    return [
        {
            "id": a.id,
            "templateName": a.template_name,
            "applyScore": a.apply_score,
            "gainScore": a.gain_score,
            "status": a.status,
            "createdAt": str(a.created_at),
        }
        for a in applications
    ]
