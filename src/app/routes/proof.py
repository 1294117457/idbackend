"""证明材料管理路由 - 兼容前端"""
from fastapi import APIRouter, Depends, Query, Path
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional

from src.app.deps import get_db
from src.app.context import get_user_id
from src.app import response as R
from src.services.proof_service import ProofService, get_proof_status_text

router = APIRouter(prefix="/api/proof", tags=["证明材料"])


class AddProofRequest(BaseModel):
    proofFileId: int
    proofValue: float = 0
    remark: Optional[str] = None
    reviewCount: Optional[int] = None


class ResubmitProofRequest(BaseModel):
    proofFileId: Optional[int] = None
    proofValue: Optional[float] = None
    remark: Optional[str] = None


@router.get("/list/{application_id}")
async def list_proofs(
    application_id: int = Path(..., description="申请ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取申请的证明材料列表"""
    proofs = await ProofService.get_by_application(db, application_id)
    if proofs is None:
        return R.forbidden_resp("无权访问")
    return R.success_resp({
        "proofs": [{
            "id": p.id,
            "applicationId": p.application_id,
            "proofFileId": p.proof_file_id,
            "proofValue": p.proof_value,
            "reviewCount": p.review_count,
            "approvedCount": p.approved_count,
            "status": p.status,
            "statusText": get_proof_status_text(p.status),
            "reviewerIds": p.reviewer_ids,
            "reviewRecords": p.review_records,
            "remark": p.remark,
            "createdAt": str(p.created_at) if p.created_at else None,
        } for p in proofs]
    })


@router.post("/{proof_id}/approve")
async def approve(
    proof_id: int = Path(..., description="证明材料ID"),
    comment: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """审核证明材料通过"""
    try:
        await ProofService.approve(db, proof_id, get_user_id(), comment)
        return R.success_resp(msg="审核通过")
    except ValueError as e:
        return R.bad_request_resp(str(e))


@router.post("/{proof_id}/reject")
async def reject(
    proof_id: int = Path(..., description="证明材料ID"),
    comment: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """审核证明材料驳回"""
    try:
        await ProofService.reject(db, proof_id, get_user_id(), comment)
        return R.success_resp(msg="已驳回")
    except ValueError as e:
        return R.bad_request_resp(str(e))


@router.post("/application/{application_id}")
async def add_proof(
    application_id: int = Path(..., description="申请ID"),
    data: AddProofRequest = ...,
    db: AsyncSession = Depends(get_db),
):
    """追加证明材料"""
    try:
        proof = await ProofService.add(
            db, application_id, get_user_id(),
            file_id=data.proofFileId,
            proof_value=data.proofValue,
            remark=data.remark,
            review_count=data.reviewCount,
        )
        return R.created_resp({"id": proof.id})
    except PermissionError:
        return R.forbidden_resp("无权操作此申请")
    except ValueError as e:
        return R.bad_request_resp(str(e))


@router.put("/{proof_id}/resubmit")
async def resubmit(
    proof_id: int = Path(..., description="证明材料ID"),
    data: ResubmitProofRequest = ...,
    db: AsyncSession = Depends(get_db),
):
    """重新提交被驳回的证明材料"""
    try:
        await ProofService.resubmit(
            db, proof_id, get_user_id(),
            file_id=data.proofFileId,
            proof_value=data.proofValue,
            remark=data.remark,
        )
        return R.success_resp(msg="重新提交成功")
    except PermissionError:
        return R.forbidden_resp("无权操作此证明材料")
    except ValueError as e:
        return R.bad_request_resp(str(e))


@router.put("/{proof_id}/override")
async def override(
    proof_id: int = Path(..., description="证明材料ID"),
    status: int = Query(..., ge=1, le=2),
    comment: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """审核员覆盖修改状态"""
    try:
        await ProofService.override_status(
            db, proof_id, get_user_id(), status, comment
        )
        return R.success_resp(msg="操作成功")
    except ValueError as e:
        return R.bad_request_resp(str(e))
