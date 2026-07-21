"""证明材料路由（v4.7 废弃审核接口）

v4.7 设计变更：
  - proof 的增删改聚合到 ApplicationPayload 中
  - proof 的审核聚合到 pass/reject 中

保留的接口：
  - GET  /api/proof/list/{application_id}    获取 proof 列表（只读）

废弃的接口（已删除）：
  - POST /api/proof/{proof_id}/approve
  - POST /api/proof/{proof_id}/reject
  - PUT  /api/proof/{proof_id}/override
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.dependencies import get_db
from src.app.context import get_user_id
from src.app import response as R

from src.services import ApplicationService
from src.models import ProofStatus


router = APIRouter(prefix="/api/proof", tags=["证明材料"])


@router.get("/list/{application_id}")
async def list_proofs(
    application_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取申请的 proof 列表"""
    user_id = get_user_id()
    if not user_id:
        return R.unauthorized_resp("未登录")

    application = await ApplicationService.get_by_id(db, application_id)
    if not application:
        return R.not_found_resp("申请不存在")
    if application.user_id != user_id:
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


def _proof_status_text(status: str) -> str:
    return {
        ProofStatus.PENDING.value: "待审核",
        ProofStatus.APPROVED.value: "已通过",
        ProofStatus.REJECTED.value: "已驳回",
    }.get(status, "未知")


__all__ = ["router"]
