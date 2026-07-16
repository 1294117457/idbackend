"""证明材料路由（v4.2 兼容入口）

v4.2 设计变更：
  - proof 是 application 的辅助表，没有独立的 CRUD
  - proof 的增删改由 save_draft / submit / resubmit 整体替换
  - proof 的状态变更由 application_service.review_proof 接管

为兼容前端老接口，保留以下薄路由：
  - GET  /api/proof/list/{application_id}    获取 proof 列表
  - POST /api/proof/{proof_id}/approve       改 proof.status = APPROVED
  - POST /api/proof/{proof_id}/reject        改 proof.status = REJECTED
  - PUT  /api/proof/{proof_id}/override      审核员覆盖（→ 同 approve/reject）

新代码应直接用 application 路由：
  - POST /api/applications/{id}/proofs/{pid}/review
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Path
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.dependencies import get_db
from src.app.context import get_user_id
from src.app import response as R

from src.services import ApplicationService
from src.models import ApplicationProof, Application, ProofStatus
from src.app.schemas.errors import NotFoundError, ConflictError

from sqlalchemy import select


router = APIRouter(prefix="/api/proof", tags=["证明材料（兼容）"])


# ════════════════════════════════════════════════════════════════════════
# 兼容入口：薄路由转发到 application_service
# ════════════════════════════════════════════════════════════════════════
class ReviewProofBody(BaseModel):
    action: str  # APPROVED | REJECTED
    remark: Optional[str] = None


@router.get("/list/{application_id}")
async def list_proofs(
    application_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取申请的 proof 列表（v4.2 兼容）"""
    user_id = get_user_id()
    if not user_id:
        return R.unauthorized_resp("未登录")

    application = await ApplicationService.get_by_id(db, application_id)
    if not application:
        return R.not_found_resp("申请不存在")
    if application.user_id != user_id:
        # 审核员也可以看，这里简化只允许本人查看
        return R.forbidden_resp("无权访问")

    return R.query_resp({
        "proofs": [
            {
                "id": p.id,
                "applicationId": p.application_id,
                "fileId": p.file_id,
                "proofScore": float(p.proof_score) if p.proof_score else 0,
                "status": p.status,
                "statusText": _proof_status_text(p.status),
                "createdAt": p.created_at.isoformat() if p.created_at else None,
            }
            for p in (application.proofs or [])
        ]
    })


@router.post("/{proof_id}/approve")
async def approve_legacy(
    proof_id: int,
    remark: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """兼容：审核通过 proof → 转发到 review_proof(action=APPROVED)"""
    user_id = get_user_id()
    if not user_id:
        return R.unauthorized_resp("未登录")

    try:
        proof = await ApplicationService.review_proof(
            db,
            proof_id=proof_id,
            reviewer_id=user_id,
            action=ProofStatus.APPROVED.value,
            remark=remark,
        )
        return R.success_resp({"id": proof.id, "status": proof.status}, msg="证明已通过")
    except NotFoundError as e:
        return R.not_found_resp(str(e))
    except ConflictError as e:
        return R._resp(409, str(e))


@router.post("/{proof_id}/reject")
async def reject_legacy(
    proof_id: int,
    remark: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """兼容：审核驳回 proof → 转发到 review_proof(action=REJECTED)"""
    user_id = get_user_id()
    if not user_id:
        return R.unauthorized_resp("未登录")

    try:
        proof = await ApplicationService.review_proof(
            db,
            proof_id=proof_id,
            reviewer_id=user_id,
            action=ProofStatus.REJECTED.value,
            remark=remark,
        )
        return R.success_resp({"id": proof.id, "status": proof.status}, msg="证明已驳回")
    except NotFoundError as e:
        return R.not_found_resp(str(e))
    except ConflictError as e:
        return R._resp(409, str(e))


@router.put("/{proof_id}/override")
async def override_legacy(
    proof_id: int,
    status: int = Query(..., ge=1, le=2),
    remark: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """兼容：审核员覆盖 status（1=APPROVED, 2=REJECTED）→ 转发到 review_proof"""
    user_id = get_user_id()
    if not user_id:
        return R.unauthorized_resp("未登录")

    action = "APPROVED" if status == 1 else "REJECTED"
    try:
        proof = await ApplicationService.review_proof(
            db,
            proof_id=proof_id,
            reviewer_id=user_id,
            action=action,
            remark=remark,
        )
        return R.success_resp({"id": proof.id, "status": proof.status}, msg="证明状态已覆盖")
    except (NotFoundError, ConflictError) as e:
        return R._resp(409 if isinstance(e, ConflictError) else 404, str(e))


def _proof_status_text(status: str) -> str:
    return {
        ProofStatus.PENDING.value: "待审核",
        ProofStatus.APPROVED.value: "已通过",
        ProofStatus.REJECTED.value: "已驳回",
    }.get(status, "未知")