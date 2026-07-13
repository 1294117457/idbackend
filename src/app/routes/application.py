"""申请路由（v4.5）

═══════════════════════════════════════════════════════════════════════
RESTful 设计（v4.5）
═══════════════════════════════════════════════════════════════════════
学生端（v4.5：3 个写接口 + proofs 整表替换，移除 4 个 proof CRUD）:
  POST   /api/applications/saveDraft              保存草稿（新建/更新 DRAFT）
  POST   /api/applications/submit                 新建并直接提交（一步到位）
  POST   /api/applications/edit-submit            编辑后提交（DRAFT/REJECTED/REVOKED → APPLYING）
  POST   /api/applications/{id}/cancel            取消草稿/申请
  POST   /api/applications/{id}/touch             纯刷 updated_at（DRAFT 专用）
  GET    /api/applications                        我的申请列表（学生）
  GET    /api/applications/{id}                   详情（含 proofs + operations）

[DEPRECATED v4.5：旧 proof CRUD 已合并到 ApplicationPayload]
  POST   /api/applications/{id}/proofs            删除
  DELETE /api/applications/{id}/proofs/{pid}      删除
  PATCH  /api/applications/{id}/proofs/{pid}      删除
  PUT    /api/applications/{id}/proofs/{pid}/file 删除
  POST   /api/applications/{id}/proofs/batch      删除
  PUT    /api/applications/{id}/draft             保留 deprecated（返回 400）
  POST   /api/applications/{id}/resubmit          保留 deprecated（返回 400）

审核员端:
  POST   /api/applications/{id}/proofs/{pid}/review       review_proof
  POST   /api/applications/{id}/pass                      pass_application
  POST   /api/applications/{id}/reject                    reject_application
  POST   /api/admin/applications/{id}/revoke              revoke_application
  GET    /api/admin/applications                          待审核列表
  GET    /api/admin/applications/history                  审核历史
  GET    /api/admin/applications/my-history               我的审核历史
  GET    /api/admin/applications/my-pending               我的待审核
  GET    /api/admin/applications/my-reviewed              我的已审核

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

from typing import Optional

from fastapi import APIRouter, Depends, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.deps import get_db
from src.app.context import get_user_id
from src.app import response as R

from src.services import (
    ApplicationService,
    ApplicationOperationService,
    TemplateService,
)
from src.models import (
    ApplicationStatus,
    ProofStatus,
)
from src.app.schemas.errors import (
    NotFoundError, BadRequestError, ConflictError, ForbiddenError,
)
from src.app.schemas import ApplicationPayload


router = APIRouter(tags=["申请"])


# ════════════════════════════════════════════════════════════════════════
# Request / Response Models（路由层用，非 Pydantic 业务模型放 schemas/）
# ════════════════════════════════════════════════════════════════════════
class ReviewProofRequest:
    """仅作占位说明；实际入参通过 Body 收
    """
    pass


from pydantic import BaseModel  # noqa: E402


class ReviewProofBody(BaseModel):
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
# 学生端 v4.5：3 个统一写接口（saveDraft / submit / edit-submit）
# ════════════════════════════════════════════════════════════════════════
@router.post("/api/applications/saveDraft")
async def save_draft(
    req: ApplicationPayload,
    db: AsyncSession = Depends(get_db),
):
    """保存草稿（v4.5）

    payload.applicationId：
      - None  → 新建 DRAFT
      - 非空  → 更新已有 DRAFT（仅本人、仅 DRAFT 状态）

    proofs 整表替换：payload.proofList 决定每条的 新建/更新/删除
    （语义见 ApplicationPayload）
    """
    user_id = get_user_id()
    if not user_id:
        return R.unauthorized_resp("未登录")

    try:
        template = await TemplateService.get_by_id(db, req.templateId)
        if not template:
            return R.not_found_resp("模板不存在")
        review_count = template.review_count or 1

        application = await ApplicationService.save_draft(
            db,
            user_id=user_id,
            payload=req,
            review_count=review_count,
        )
        return R.created_resp(format_application(application), msg="草稿保存成功")
    except ConflictError as e:
        return R.conflict_resp(str(e))
    except (NotFoundError, BadRequestError) as e:
        return R.bad_request_resp(str(e))
    except Exception as e:
        return R.server_error_resp(f"保存草稿失败: {e}")


@router.post("/api/applications/submit")
async def submit(
    req: ApplicationPayload,
    db: AsyncSession = Depends(get_db),
):
    """新建并提交（v4.5）

    payload.applicationId 必须为 None。
    直接 INSERT application（status='APPLYING'）+ 整批 proofs。
    """
    user_id = get_user_id()
    if not user_id:
        return R.unauthorized_resp("未登录")

    try:
        template = await TemplateService.get_by_id(db, req.templateId)
        if not template:
            return R.not_found_resp("模板不存在")
        review_count = template.review_count or 1

        operator_name = await _get_user_full_name(db, user_id)
        application = await ApplicationService.submit(
            db,
            user_id=user_id,
            payload=req,
            operator_name=operator_name,
            review_count=review_count,
        )
        return R.created_resp(format_application(application), msg="申请已提交")
    except ConflictError as e:
        return R.conflict_resp(str(e))
    except (NotFoundError, BadRequestError) as e:
        return R.bad_request_resp(str(e))
    except Exception as e:
        return R.server_error_resp(f"提交失败: {e}")


@router.post("/api/applications/edit-submit")
async def edit_submit(
    req: ApplicationPayload,
    db: AsyncSession = Depends(get_db),
):
    """编辑后提交（v4.5）

    payload.applicationId 必须非空。仅 DRAFT/REJECTED/REVOKED 可编辑并提交。
    proofs 整表替换 + status 推进到 APPLYING。
    """
    user_id = get_user_id()
    if not user_id:
        return R.unauthorized_resp("未登录")

    try:
        operator_name = await _get_user_full_name(db, user_id)
        application = await ApplicationService.edit_submit(
            db,
            user_id=user_id,
            payload=req,
            operator_name=operator_name,
        )
        return R.created_resp(format_application(application), msg="申请已提交")
    except ConflictError as e:
        return R.conflict_resp(str(e))
    except (NotFoundError, BadRequestError) as e:
        return R.bad_request_resp(str(e))
    except Exception as e:
        return R.server_error_resp(f"编辑提交失败: {e}")


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
        return R.success_resp({"id": application.id, "status": application.status}, msg="申请已取消")
    except (NotFoundError, ForbiddenError, ConflictError) as e:
        return R.forbidden_resp(str(e))


@router.post("/api/applications/{application_id}/touch")
async def touch_application(
    application_id: int,
    db: AsyncSession = Depends(get_db),
):
    """[v4.4 新增] DRAFT 状态下纯刷 updated_at"""
    user_id = get_user_id()
    if not user_id:
        return R.unauthorized_resp("未登录")

    try:
        application = await ApplicationService.touch(
            db,
            application_id=application_id,
            user_id=user_id,
        )
        return R.success_resp(format_application(application), msg="草稿已保存")
    except (NotFoundError, ForbiddenError, ConflictError, BadRequestError) as e:
        code = e.__class__.__name__
        if code == "ForbiddenError":
            return R.forbidden_resp(str(e))
        if code == "ConflictError":
            return R.conflict_resp(str(e))
        if code == "BadRequestError":
            return R.bad_request_resp(str(e))
        return R.not_found_resp(str(e))


# ════════════════════════════════════════════════════════════════════════
# [DEPRECATED] 旧的 5 个 proof CRUD/batch 路由 + 旧的 draft / resubmit
# （保留 deprecated marker 兜底历史调用方，前端已不再使用）
# ════════════════════════════════════════════════════════════════════════
@router.post("/api/applications/{application_id}/proofs", deprecated=True)
async def _deprecated_create_proof(application_id: int):
    return R.bad_request_resp(
        "新增 proof 接口已废弃（v4.5），请改用 POST /api/applications/saveDraft 或 /edit-submit 整表替换 proofs"
    )


@router.delete("/api/applications/{application_id}/proofs/{proof_id}", deprecated=True)
async def _deprecated_delete_proof(application_id: int, proof_id: int):
    return R.bad_request_resp(
        "删除 proof 接口已废弃（v4.5），请在 payload.proofList 中省略 proofId 即视为删除"
    )


@router.patch("/api/applications/{application_id}/proofs/{proof_id}", deprecated=True)
async def _deprecated_update_proof_score(application_id: int, proof_id: int):
    return R.bad_request_resp(
        "修改 proof 接口已废弃（v4.5），请在 payload.proofList 中携带 proofId 即可更新"
    )


@router.put("/api/applications/{application_id}/proofs/{proof_id}/file", deprecated=True)
async def _deprecated_replace_proof_file(application_id: int, proof_id: int):
    return R.bad_request_resp(
        "重传 proof 文件接口已废弃（v4.5），请在 payload.proofList 中修改对应 proof 的 fileId 即可"
    )


@router.post("/api/applications/{application_id}/proofs/batch", deprecated=True)
async def _deprecated_save_proofs(application_id: int):
    return R.bad_request_resp(
        "批量保存 proofs 接口已废弃（v4.5），请改用 POST /api/applications/saveDraft 或 /edit-submit"
    )


@router.put("/api/applications/{application_id}/draft", deprecated=True)
async def _deprecated_update_draft(application_id: int):
    return R.bad_request_resp(
        "旧 update_draft 已废弃（v4.5），请改用 POST /api/applications/saveDraft"
    )


@router.post("/api/applications/{application_id}/resubmit", deprecated=True)
async def _deprecated_resubmit(application_id: int):
    return R.bad_request_resp(
        "resubmit 已废弃（v4.5），请改用 POST /api/applications/edit-submit"
    )


@router.post("/api/applications/{application_id}/submit", deprecated=True)
async def _deprecated_old_submit(application_id: int):
    return R.bad_request_resp(
        "旧 submit 已废弃（v4.5），请改用 POST /api/applications/edit-submit"
    )


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
    return R.query_resp({
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
    return R.query_resp({
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
    req: ReviewProofBody,
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
        }, msg="审核已记录")
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
        }, msg="审核通过")
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
        }, msg="已驳回")
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
        }, msg="已撤回")
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
    return R.query_resp({
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
    return R.query_resp({
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
    return R.query_resp({
        "list": [format_application(a) for a in applications],
        "total": total,
        "pageNum": pageNum,
        "pageSize": pageSize,
    })


@router.get("/api/admin/applications/my-pending")
async def list_my_pending(
    pageNum: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """当前审核员的待审核列表（排除 reviewer_ids 包含自己的人）"""
    user_id = get_user_id()
    if not user_id:
        return R.unauthorized_resp("未登录")

    applications, total = await ApplicationService.list_pending_for_me(
        db, user_id, pageNum, pageSize,
    )
    return R.query_resp({
        "list": [format_application(a, with_proofs=True) for a in applications],
        "total": total,
        "pageNum": pageNum,
        "pageSize": pageSize,
    })


@router.get("/api/admin/applications/my-reviewed")
async def list_my_reviewed(
    pageNum: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """当前审核员的历史审核列表（reviewer_ids 包含自己）"""
    user_id = get_user_id()
    if not user_id:
        return R.unauthorized_resp("未登录")

    applications, total = await ApplicationService.list_my_reviewed(
        db, user_id, pageNum, pageSize,
    )
    return R.query_resp({
        "list": [format_application(a, with_proofs=True) for a in applications],
        "total": total,
        "pageNum": pageNum,
        "pageSize": pageSize,
    })


# ════════════════════════════════════════════════════════════════════════
# 格式化工具
# ════════════════════════════════════════════════════════════════════════
def format_application(a, with_proofs: bool = False) -> dict:
    """格式化 application（前后端约定 camelCase）"""
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
        "reviewerIds": a.reviewer_ids or [],
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
