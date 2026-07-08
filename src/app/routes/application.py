"""申请路由（v4.3）

═══════════════════════════════════════════════════════════════════════
RESTful 设计
═══════════════════════════════════════════════════════════════════════
学生端:
  POST   /api/applications/draft                  save_draft
  POST   /api/applications/{id}/cancel            cancel（取消草稿/申请）
  POST   /api/applications/{id}/submit            submit
  POST   /api/applications/{id}/resubmit          resubmit
  GET    /api/applications                        我的申请列表（学生）
  GET    /api/applications/{id}                   详情（含 proofs + operations）

审核员端:
  POST   /api/applications/{id}/proofs/{pid}/review   review_proof
  POST   /api/applications/{id}/pass                  pass_application
  POST   /api/applications/{id}/reject                reject_application
  POST   /api/applications/{id}/revoke               revoke_application
  GET    /api/admin/applications                      待审核列表
  GET    /api/admin/applications/history              审核历史

状态语义：
  DRAFT      - 草稿（学生可编辑）
  APPLYING   - 审核中（学生锁定）
  PASSED     - 已通过（终态）
  REJECTED   - 已驳回（可重提）
  CANCELLED  - 已取消（终态，学生主动取消）
  REVOKED    - 已撤回（终态，老师撤回）
═══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

from typing import Optional, List
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Path, Body
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.deps import get_db
from src.app.context import get_user_id
from src.app import response as R

from src.services import (
    ApplicationService,
    ApplicationOperationService,
    ScoreDataService,
    TemplateService,
)
from src.models import (
    ApplicationStatus,
    ProofStatus,
)
from src.app.schemas.errors import (
    NotFoundError, BadRequestError, ConflictError, ForbiddenError,
)


router = APIRouter(tags=["申请"])


# ════════════════════════════════════════════════════════════════════════
# Request / Response Models
# ════════════════════════════════════════════════════════════════════════
class ProofDataItem(BaseModel):
    file_id: Optional[int] = None
    proof_score: float


class SaveDraftRequest(BaseModel):
    template_id: int
    template_name: str
    category_id: int
    apply_score: float
    proof_data_list: List[ProofDataItem] = Field(default_factory=list)
    remark: Optional[str] = None
    # review_count 不接受客户端传值，由路由从 template 读取


class UpdateDraftRequest(BaseModel):
    proof_data_list: List[ProofDataItem]


class ResubmitRequest(BaseModel):
    proof_data_list: List[ProofDataItem]


class ReviewProofRequest(BaseModel):
    action: str  # APPROVED | REJECTED
    remark: Optional[str] = None


class VoteRequest(BaseModel):
    remark: Optional[str] = None


class RejectRequest(BaseModel):
    remark: str   # 必填


class CancelRequest(BaseModel):
    remark: Optional[str] = None


# ════════════════════════════════════════════════════════════════════════
# 工具：构造 operator_name
# ════════════════════════════════════════════════════════════════════════
async def _get_user_full_name(db: AsyncSession, user_id: int) -> str:
    from src.models import User
    user = await db.get(User, user_id)
    return (user.full_name if user else None) or (user.username if user else f"user#{user_id}")


# ════════════════════════════════════════════════════════════════════════
# 学生端：草稿 / 提交 / 取消 / 重提
# ════════════════════════════════════════════════════════════════════════
@router.post("/api/applications/draft")
async def save_draft(
    req: SaveDraftRequest,
    db: AsyncSession = Depends(get_db),
):
    """保存草稿（v4.3：允许同模板多草稿，review_count 从模板读取）"""
    user_id = get_user_id()
    if not user_id:
        return R.unauthorized_resp("未登录")

    try:
        # 从模板读取 review_count（不信任客户端）
        template = await TemplateService.get_by_id(db, req.template_id)
        if not template:
            return R.not_found_resp("模板不存在")
        review_count = template.review_count or 1

        application = await ApplicationService.save_draft(
            db,
            user_id=user_id,
            template_id=req.template_id,
            template_name=req.template_name,
            category_id=req.category_id,
            apply_score=Decimal(str(req.apply_score)),
            proof_data_list=[p.model_dump() for p in req.proof_data_list],
            review_count=review_count,
            remark=req.remark,
        )
        return R.created_resp(format_application(application))
    except ConflictError as e:
        return R.conflict_resp(str(e))
    except (NotFoundError, BadRequestError) as e:
        return R.bad_request_resp(str(e))
    except Exception as e:
        return R.server_error_resp(f"保存草稿失败: {e}")


@router.put("/api/applications/{application_id}/draft")
async def update_draft(
    application_id: int,
    req: UpdateDraftRequest,
    db: AsyncSession = Depends(get_db),
):
    """更新草稿（DRAFT/REVOKED/REJECTED → 替换 proof 列表）"""
    user_id = get_user_id()
    if not user_id:
        return R.unauthorized_resp("未登录")

    try:
        application = await ApplicationService.update_draft(
            db,
            application_id=application_id,
            user_id=user_id,
            proof_data_list=[p.model_dump() for p in req.proof_data_list],
        )
        return R.success_resp(format_application(application))
    except (NotFoundError, ForbiddenError, ConflictError, BadRequestError) as e:
        code = e.__class__.__name__
        if code == "ForbiddenError":
            return R.forbidden_resp(str(e))
        if code == "ConflictError":
            return R.conflict_resp(str(e))
        if code == "BadRequestError":
            return R.bad_request_resp(str(e))
        return R.not_found_resp(str(e))


@router.post("/api/applications/{application_id}/cancel")
async def cancel_application(
    application_id: int,
    req: CancelRequest = Body(default=CancelRequest()),
    db: AsyncSession = Depends(get_db),
):
    """取消草稿/申请（DRAFT/APPLYING → CANCELLED）"""
    user_id = get_user_id()
    if not user_id:
        return R.unauthorized_resp("未登录")

    try:
        operator_name = await _get_user_full_name(db, user_id)
        application = await ApplicationService.cancel(
            db,
            application_id=application_id,
            user_id=user_id,
            operator_name=operator_name,
            remark=req.remark,
        )
        return R.success_resp({"id": application.id, "status": application.status})
    except (NotFoundError, ForbiddenError, ConflictError) as e:
        return R.forbidden_resp(str(e))


@router.post("/api/applications/{application_id}/submit")
async def submit_application(
    application_id: int,
    db: AsyncSession = Depends(get_db),
):
    """DRAFT → APPLYING"""
    user_id = get_user_id()
    if not user_id:
        return R.unauthorized_resp("未登录")

    try:
        operator_name = await _get_user_full_name(db, user_id)
        application = await ApplicationService.submit(
            db,
            application_id=application_id,
            user_id=user_id,
            operator_name=operator_name,
        )
        return R.success_resp(format_application(application))
    except (NotFoundError, ForbiddenError, ConflictError, BadRequestError) as e:
        code = e.__class__.__name__
        if code == "ForbiddenError":
            return R.forbidden_resp(str(e))
        if code in ("NotFoundError", "ConflictError"):
            return R.not_found_resp(str(e))
        return R.bad_request_resp(str(e))


@router.post("/api/applications/{application_id}/resubmit")
async def resubmit_application(
    application_id: int,
    req: ResubmitRequest,
    db: AsyncSession = Depends(get_db),
):
    """REJECTED → APPLYING（整体替换 proof 列表）"""
    user_id = get_user_id()
    if not user_id:
        return R.unauthorized_resp("未登录")

    try:
        operator_name = await _get_user_full_name(db, user_id)
        application = await ApplicationService.resubmit(
            db,
            application_id=application_id,
            user_id=user_id,
            operator_name=operator_name,
            proof_data_list=[p.model_dump() for p in req.proof_data_list],
        )
        return R.success_resp(format_application(application))
    except (NotFoundError, ForbiddenError, ConflictError, BadRequestError) as e:
        code = e.__class__.__name__
        if code == "ForbiddenError":
            return R.forbidden_resp(str(e))
        if code == "BadRequestError":
            return R.bad_request_resp(str(e))
        return R.not_found_resp(str(e))


# ════════════════════════════════════════════════════════════════════════
# 学生端：列表 / 详情
# ════════════════════════════════════════════════════════════════════════
@router.get("/api/applications")
async def list_my_applications(
    status: Optional[str] = Query(None),
    pageNum: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """我的申请列表（学生）"""
    user_id = get_user_id()
    if not user_id:
        return R.unauthorized_resp("未登录")

    applications, total = await ApplicationService.list_user_applications(
        db, user_id, status, pageNum, pageSize,
    )
    return R.success_resp({
        "list": [format_application(a) for a in applications],
        "total": total,
        "pageNum": pageNum,
        "pageSize": pageSize,
    })


@router.get("/api/applications/{application_id}")
async def get_application_detail(
    application_id: int,
    db: AsyncSession = Depends(get_db),
):
    """申请详情（含 proofs + operations）"""
    application = await ApplicationService.get_by_id(db, application_id)
    if not application:
        return R.not_found_resp("申请不存在")

    operations = await ApplicationOperationService.list_by_application(db, application_id)
    return R.success_resp({
        **format_application(application, with_proofs=True),
        "operations": [format_operation(o) for o in operations],
    })


# ════════════════════════════════════════════════════════════════════════
# 审核员端：审核 / 投票 / 列表
# ════════════════════════════════════════════════════════════════════════
@router.post("/api/applications/{application_id}/proofs/{proof_id}/review")
async def review_proof(
    application_id: int,
    proof_id: int,
    req: ReviewProofRequest,
    db: AsyncSession = Depends(get_db),
):
    """审核员改 proof.status（任意审核员可覆盖）"""
    user_id = get_user_id()
    if not user_id:
        return R.unauthorized_resp("未登录")

    try:
        proof = await ApplicationService.review_proof(
            db,
            proof_id=proof_id,
            reviewer_id=user_id,
            action=req.action,
            remark=req.remark,
        )
        return R.success_resp({
            "id": proof.id,
            "applicationId": proof.application_id,
            "status": proof.status,
        })
    except NotFoundError as e:
        return R.not_found_resp(str(e))
    except BadRequestError as e:
        return R.bad_request_resp(str(e))
    except ConflictError as e:
        return R.conflict_resp(str(e))


@router.post("/api/applications/{application_id}/pass")
async def pass_application(
    application_id: int,
    req: VoteRequest = Body(default=VoteRequest()),
    db: AsyncSession = Depends(get_db),
):
    """审核员投 PASS application"""
    user_id = get_user_id()
    if not user_id:
        return R.unauthorized_resp("未登录")

    try:
        operator_name = await _get_user_full_name(db, user_id)
        application = await ApplicationService.pass_application(
            db,
            application_id=application_id,
            reviewer_id=user_id,
            reviewer_name=operator_name,
            remark=req.remark,
        )
        return R.success_resp({
            "id": application.id,
            "status": application.status,
            "approvedCount": application.approved_count,
            "reviewCount": application.review_count,
            "gainScore": float(application.gain_score) if application.gain_score else None,
        })
    except (NotFoundError, ConflictError, BadRequestError) as e:
        if isinstance(e, ConflictError):
            return R.conflict_resp(str(e))
        return R.bad_request_resp(str(e))


@router.post("/api/applications/{application_id}/reject")
async def reject_application(
    application_id: int,
    req: RejectRequest,
    db: AsyncSession = Depends(get_db),
):
    """审核员 REJECT application（veto）"""
    user_id = get_user_id()
    if not user_id:
        return R.unauthorized_resp("未登录")

    try:
        operator_name = await _get_user_full_name(db, user_id)
        application = await ApplicationService.reject_application(
            db,
            application_id=application_id,
            reviewer_id=user_id,
            reviewer_name=operator_name,
            remark=req.remark,
        )
        return R.success_resp({
            "id": application.id,
            "status": application.status,
            "rejectedCount": application.rejected_count,
        })
    except (NotFoundError, ConflictError, BadRequestError) as e:
        if isinstance(e, ConflictError):
            return R.conflict_resp(str(e))
        return R.bad_request_resp(str(e))


@router.post("/api/admin/applications/{application_id}/revoke")
async def revoke_application(
    application_id: int,
    req: RejectRequest,
    db: AsyncSession = Depends(get_db),
):
    """审核员撤回已通过的申请（PASSED → REJECTED）"""
    user_id = get_user_id()
    if not user_id:
        return R.unauthorized_resp("未登录")

    try:
        operator_name = await _get_user_full_name(db, user_id)
        application = await ApplicationService.revoke(
            db,
            application_id=application_id,
            operator_id=user_id,
            operator_name=operator_name,
            remark=req.remark,
        )
        return R.success_resp({
            "id": application.id,
            "status": application.status,
        })
    except (NotFoundError, BadRequestError) as e:
        return R.bad_request_resp(str(e))


@router.get("/api/admin/applications")
async def list_pending_applications(
    pageNum: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """审核员：待审核列表（status=APPLYING）"""
    applications, total = await ApplicationService.list_pending_applications(
        db, pageNum, pageSize,
    )
    return R.success_resp({
        "list": [format_application(a, with_proofs=True) for a in applications],
        "total": total,
        "pageNum": pageNum,
        "pageSize": pageSize,
    })


@router.get("/api/admin/applications/history")
async def list_audit_history(
    pageNum: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """审核员：审核历史（所有终态）"""
    applications, total = await ApplicationService.list_audit_history(
        db, pageNum, pageSize,
    )
    return R.success_resp({
        "list": [format_application(a) for a in applications],
        "total": total,
        "pageNum": pageNum,
        "pageSize": pageSize,
    })


@router.get("/api/admin/applications/my-history")
async def list_my_audit_history(
    pageNum: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """当前审核员操作过的申请（按最新操作时间排序）"""
    user_id = get_user_id()
    if not user_id:
        return R.unauthorized_resp("未登录")

    applications, total = await ApplicationService.list_my_audit_history(
        db, user_id, pageNum, pageSize,
    )
    return R.success_resp({
        "list": [format_application(a) for a in applications],
        "total": total,
        "pageNum": pageNum,
        "pageSize": pageSize,
    })


# ════════════════════════════════════════════════════════════════════════
# 格式化工具
# ════════════════════════════════════════════════════════════════════════
def format_application(a, with_proofs: bool = False) -> dict:
    """格式化 application（前后端约定 camelCase）"""
    # 尝试从 user 关联读取姓名（service 已用 selectinload 加载）
    user_name: Optional[str] = None
    if hasattr(a, 'user') and a.user:
        u = a.user
        user_name = getattr(u, 'full_name', None) or getattr(u, 'username', None) or f"user#{a.user_id}"

    base = {
        "id": a.id,
        "userId": a.user_id,
        "userName": user_name,
        "templateId": a.template_id,
        "templateName": a.template_name,
        "categoryId": a.category_id,
        "applyScore": float(a.apply_score) if a.apply_score else 0,
        "gainScore": float(a.gain_score) if a.gain_score else 0,
        "status": a.status,
        "statusText": get_application_status_text(a.status),
        "reviewCount": a.review_count or 1,
        "approvedCount": a.approved_count or 0,
        "rejectedCount": a.rejected_count or 0,
        "createdAt": a.created_at.isoformat() if a.created_at else None,
        "updatedAt": a.updated_at.isoformat() if a.updated_at else None,
    }
    if with_proofs:
        base["proofs"] = [
            {
                "id": p.id,
                "applicationId": p.application_id,
                "fileId": p.file_id,
                "proofScore": float(p.proof_score) if p.proof_score else 0,
                "status": p.status,
                "statusText": get_proof_status_text(p.status),
                "createdAt": p.created_at.isoformat() if p.created_at else None,
            }
            for p in (a.proofs or [])
        ]
    return base


def format_operation(o) -> dict:
    return {
        "id": o.id,
        "applicationId": o.application_id,
        "operatorId": o.operator_id,
        "operatorName": o.operator_name,
        "operation": o.operation,
        "remark": o.remark,
        "createdAt": o.created_at.isoformat() if o.created_at else None,
    }


def get_application_status_text(status: str) -> str:
    return {
        ApplicationStatus.DRAFT.value: "草稿",
        ApplicationStatus.APPLYING.value: "审核中",
        ApplicationStatus.PASSED.value: "已通过",
        ApplicationStatus.REJECTED.value: "已驳回",
        ApplicationStatus.CANCELLED.value: "已取消",
        ApplicationStatus.REVOKED.value: "已撤回",
    }.get(status, "未知")


def get_proof_status_text(status: str) -> str:
    return {
        ProofStatus.PENDING.value: "待审核",
        ProofStatus.APPROVED.value: "已通过",
        ProofStatus.REJECTED.value: "已驳回",
    }.get(status, "未知")