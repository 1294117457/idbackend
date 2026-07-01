"""申请路由 - 兼容前端"""
from fastapi import APIRouter, Depends, Query, Path, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from pydantic import BaseModel
from typing import Optional, List

from src.app.deps import get_db, get_current_user, CurrentUser, require_reviewer
from src.app.response import success_response, error_response
from src.services import ApplicationService, TemplateService

router = APIRouter(prefix="/api/application", tags=["申请"])


# ========== 请求/响应模型 ==========

class ProofItem(BaseModel):
    proofFileId: int
    proofValue: float
    reviewCount: Optional[int] = 1
    remark: Optional[str] = None


class SubmitApplicationRequest(BaseModel):
    studentId: str
    studentName: str
    major: str
    enrollmentYear: int
    templateName: str
    templateType: str
    scoreType: int
    applyScore: float
    applyInput: Optional[float] = None
    ruleId: Optional[int] = None
    reviewCount: int = 1
    proofItems: List[ProofItem] = []
    remark: Optional[str] = None


class ReviewRequest(BaseModel):
    comment: Optional[str] = None


# ========== 用户接口 ==========

@router.post("/submit")
async def submit_application(
    request: SubmitApplicationRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """提交加分申请"""
    # 查找模板
    templates = await TemplateService.get_templates(db)
    template = next((t for t in templates if t.template_name == request.templateName), None)

    if not template:
        return error_response("模板不存在", code=404)

    # 创建申请
    application = await ApplicationService.create_application(
        db,
        user_id=user.user_id,
        template_id=template.id,
        template_name=request.templateName,
        apply_score=request.applyScore,
        rule_id=request.ruleId,
        apply_input=request.applyInput,
        score_type=request.scoreType,
    )

    # 添加证明材料
    for proof in request.proofItems:
        await ApplicationService.add_proof(
            db, application.id, proof.proofFileId, proof.proofValue
        )

    return success_response({
        "applicationId": application.id,
        "status": "pending",
    })


@router.get("/my-records")
async def get_my_records(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取我的申请记录"""
    applications, _ = await ApplicationService.get_user_applications(db, user.user_id)

    return success_response([{
        "id": a.id,
        "studentName": a.student_name,
        "templateName": a.template_name,
        "applyScore": a.apply_score,
        "gainScore": a.gain_score,
        "status": a.status,
        "createdAt": str(a.created_at),
    } for a in applications])


@router.delete("/cancel/{record_id}")
async def cancel_application(
    record_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """取消申请"""
    result = await ApplicationService.cancel_application(db, record_id, user.user_id)
    if not result:
        return error_response("申请不存在或无法取消", code=400)
    return success_response(msg="取消成功")


@router.post("/resubmit/{record_id}")
async def resubmit_application(
    record_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """重新提交已驳回的申请"""
    application = await ApplicationService.resubmit_application(db, record_id, user.user_id)
    if not application:
        return error_response("申请不存在或无法重新提交", code=400)
    return success_response(msg="重新提交成功")


# ========== 审核员接口 ==========

@router.get("/pending")
async def get_pending(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: CurrentUser = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
):
    """获取待审核列表"""
    applications, total = await ApplicationService.get_pending_applications(db, page, size)
    return success_response({
        "list": [{
            "id": a.id,
            "studentName": a.student_name,
            "templateName": a.template_name,
            "applyScore": a.apply_score,
            "gainScore": a.gain_score,
            "status": a.status,
            "createdAt": str(a.created_at),
        } for a in applications],
        "total": total,
    })


# ========== 审核员接口 ==========

class AuditRequest(BaseModel):
    recordId: int
    comment: Optional[str] = None


class RevokeRequest(BaseModel):
    recordId: int
    reason: str


@router.get("/audit/pending")
async def get_pending_applications(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    studentId: Optional[str] = Query(None),
    studentName: Optional[str] = Query(None),
    major: Optional[str] = Query(None),
    _: CurrentUser = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
):
    """分页获取待审核列表"""
    applications, total = await ApplicationService.get_pending_applications_paged(
        db, page, size, studentId, studentName, major
    )
    return success_response({
        "records": [format_application(a) for a in applications],
        "total": total,
    })


@router.get("/audit/history")
async def get_audit_history(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    studentId: Optional[str] = Query(None),
    studentName: Optional[str] = Query(None),
    major: Optional[str] = Query(None),
    _: CurrentUser = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
):
    """分页获取审核历史"""
    applications, total = await ApplicationService.get_audit_history_paged(
        db, page, size, studentId, studentName, major
    )
    return success_response({
        "records": [format_application(a) for a in applications],
        "total": total,
    })


@router.post("/audit/approve")
async def approve_application(
    request: AuditRequest,
    user: CurrentUser = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
):
    """审核通过"""
    application = await ApplicationService.approve_application(
        db, request.recordId, user.user_id, request.comment
    )
    if not application:
        return error_response("申请不存在", code=404)
    return success_response(msg="审核通过")


@router.post("/audit/reject")
async def reject_application(
    request: AuditRequest,
    user: CurrentUser = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
):
    """审核驳回"""
    application = await ApplicationService.reject_application(
        db, request.recordId, user.user_id, request.comment
    )
    if not application:
        return error_response("申请不存在", code=404)
    return success_response(msg="已驳回")


@router.post("/audit/revoke")
async def revoke_application(
    request: RevokeRequest,
    user: CurrentUser = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
):
    """撤销已通过的申请"""
    result = await ApplicationService.revoke_application(
        db, request.recordId, user.user_id, request.reason
    )
    if not result:
        return error_response("撤销失败", code=400)
    return success_response(msg="撤销成功")


def format_application(a) -> dict:
    """格式化申请记录"""
    from src.services import TemplateService
    template_type = TemplateService.get_template_type_by_name(a.template_name) if a.template_name else "CONDITION"
    return {
        "id": a.id,
        "studentId": a.student_id or "",
        "studentName": a.student_name or "",
        "major": a.major or "",
        "enrollmentYear": a.enrollment_year or 0,
        "templateName": a.template_name or "",
        "templateType": template_type,
        "scoreType": a.score_type or 0,
        "applyScore": float(a.apply_score) if a.apply_score else 0,
        "applyInput": float(a.apply_input) if a.apply_input else None,
        "proofsInput": float(a.proofs_input) if a.proofs_input else 0,
        "gainScore": float(a.gain_score) if a.gain_score else None,
        "status": a.status or 0,
        "statusText": get_status_text(a.status),
        "submitTime": a.created_at.strftime("%Y-%m-%d %H:%M:%S") if a.created_at else None,
        "remark": a.remark,
        "reviewCount": a.review_count or 1,
        "currentReviewCount": a.current_review_count or 0,
        "reviewRecords": a.review_records,
    }


def get_status_text(status: int) -> str:
    return {0: "待审核", 1: "已通过", 2: "已驳回", 4: "已撤销"}.get(status, "未知")
