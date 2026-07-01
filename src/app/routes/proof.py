"""证明材料管理路由 - 兼容前端"""
from fastapi import APIRouter, Depends, Query, Path
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional

from src.app.deps import get_db, CurrentUser, require_reviewer
from src.app.response import success_response, error_response
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
    user: CurrentUser = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
):
    """获取申请的证明材料列表"""
    proofs = await ProofService.get_by_application(db, application_id)
    if proofs is None:
        return error_response("无权访问", code=403)
    return success_response({
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
    user: CurrentUser = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
):
    """审核证明材料通过"""
    try:
        await ProofService.approve(db, proof_id, user.user_id, comment)
        return success_response(msg="审核通过")
    except ValueError as e:
        return error_response(str(e))
    except Exception as e:
        return error_response(f"审核失败: {str(e)}")


@router.post("/{proof_id}/reject")
async def reject(
    proof_id: int = Path(..., description="证明材料ID"),
    comment: Optional[str] = Query(None),
    user: CurrentUser = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
):
    """审核证明材料驳回"""
    try:
        await ProofService.reject(db, proof_id, user.user_id, comment)
        return success_response(msg="已驳回")
    except ValueError as e:
        return error_response(str(e))
    except Exception as e:
        return error_response(f"驳回失败: {str(e)}")


@router.post("/application/{application_id}")
async def add_proof(
    application_id: int = Path(..., description="申请ID"),
    data: AddProofRequest = ...,
    user: CurrentUser = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
):
    """追加证明材料"""
    try:
        proof = await ProofService.add(
            db, application_id, user.user_id,
            file_id=data.proofFileId,
            proof_value=data.proofValue,
            remark=data.remark,
            review_count=data.reviewCount,
        )
        return success_response({"id": proof.id})
    except PermissionError:
        return error_response("无权操作此申请", code=403)
    except ValueError as e:
        return error_response(str(e))
    except Exception as e:
        return error_response(f"追加失败: {str(e)}")


@router.put("/{proof_id}/resubmit")
async def resubmit(
    proof_id: int = Path(..., description="证明材料ID"),
    data: ResubmitProofRequest = ...,
    user: CurrentUser = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
):
    """重新提交被驳回的证明材料"""
    try:
        await ProofService.resubmit(
            db, proof_id, user.user_id,
            file_id=data.proofFileId,
            proof_value=data.proofValue,
            remark=data.remark,
        )
        return success_response(msg="重新提交成功")
    except PermissionError:
        return error_response("无权操作此证明材料", code=403)
    except ValueError as e:
        return error_response(str(e))
    except Exception as e:
        return error_response(f"重新提交失败: {str(e)}")


@router.put("/{proof_id}/override")
async def override(
    proof_id: int = Path(..., description="证明材料ID"),
    status: int = Query(..., ge=1, le=2),
    comment: Optional[str] = Query(None),
    user: CurrentUser = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
):
    """审核员覆盖修改状态"""
    try:
        await ProofService.override_status(
            db, proof_id, user.user_id, status, comment
        )
        return success_response(msg="操作成功")
    except ValueError as e:
        return error_response(str(e))
    except Exception as e:
        return error_response(f"操作失败: {str(e)}")
