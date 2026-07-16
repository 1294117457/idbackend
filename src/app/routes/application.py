"""申请路由

职责：只做接收接口数据、传递给 service、返回对应数据。
认证、contextvar 操作、异常处理由中间件统一处理。
"""
from typing import Optional, Annotated

from fastapi import APIRouter, Depends, Query, Body, Path
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.dependencies import get_db
from src.app import response as R
from src.app.schemas import (
    ApplicationPayload,
    ApplicationVO,
    ApplicationDetailVO,
    ApplicationListVO,
    ApplicationQueryRequest,
)
from src.services import ApplicationService


router = APIRouter(tags=["申请"])


# ════════════════════════════════════════════════════════════════════════
# 学生端：草稿 / 提交
# ════════════════════════════════════════════════════════════════════════

@router.post("/api/applications/saveDraft", status_code=201)
async def save_draft(
    req: ApplicationPayload,
    db: AsyncSession = Depends(get_db),
):
    """保存草稿（新建或更新 DRAFT）"""
    vo = await ApplicationService.save_draft(db, req)
    return R.created_resp(vo.model_dump(), msg="草稿保存成功")


@router.post("/api/applications/submit", status_code=201)
async def submit(
    req: ApplicationPayload,
    db: AsyncSession = Depends(get_db),
):
    """新建并提交申请"""
    vo = await ApplicationService.submit(db, req)
    return R.created_resp(vo.model_dump(), msg="申请已提交")


@router.post("/api/applications/edit-submit", status_code=201)
async def edit_submit(
    req: ApplicationPayload,
    db: AsyncSession = Depends(get_db),
):
    """编辑后提交"""
    vo = await ApplicationService.edit_submit(db, req)
    return R.created_resp(vo.model_dump(), msg="申请已提交")


@router.post("/api/applications/{application_id}/cancel")
async def cancel_application(
    application_id: int = Path(..., description="申请ID"),
    req: dict = Body(default={}),
    db: AsyncSession = Depends(get_db),
):
    """取消申请"""
    remark = req.get("remark")
    vo = await ApplicationService.cancel(db, application_id, remark=remark)
    return R.success_resp(vo.model_dump(), msg="申请已取消")


@router.post("/api/applications/{application_id}/touch")
async def touch_application(
    application_id: int = Path(..., description="申请ID"),
    db: AsyncSession = Depends(get_db),
):
    """DRAFT 状态下纯刷 updated_at"""
    vo = await ApplicationService.touch(db, application_id)
    return R.success_resp(vo.model_dump(), msg="草稿已保存")


# ════════════════════════════════════════════════════════════════════════
# 学生端：列表 / 详情
# ════════════════════════════════════════════════════════════════════════

@router.get("/api/applications")
async def list_my_applications(
    status: Optional[str] = Query(None, description="状态过滤"),
    pageNum: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """我的申请列表"""
    page = await ApplicationService.list_my_applications(db, status, pageNum, pageSize)
    return R.query_resp(page.model_dump())


@router.get("/api/applications/{application_id}")
async def get_application_detail(
    application_id: int = Path(..., description="申请ID"),
    db: AsyncSession = Depends(get_db),
):
    """申请详情（含 proofs + operations）"""
    vo = await ApplicationService.get_detail(db, application_id)
    return R.query_resp(vo.model_dump())


# ════════════════════════════════════════════════════════════════════════
# 审核员端：审核 / 投票
# ════════════════════════════════════════════════════════════════════════

@router.post("/api/applications/{application_id}/proofs/{proof_id}/review")
async def review_proof(
    application_id: int = Path(..., description="申请ID"),
    proof_id: int = Path(..., description="证明ID"),
    req: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """审核 proof（APPROVED 或 REJECTED）"""
    result = await ApplicationService.review_proof(
        db, application_id, proof_id, req.get("action"), req.get("remark"),
    )
    return R.success_resp(result, msg="审核已记录")


@router.post("/api/applications/{application_id}/pass")
async def pass_application(
    application_id: int = Path(..., description="申请ID"),
    req: dict = Body(default={}),
    db: AsyncSession = Depends(get_db),
):
    """审核员投 PASS"""
    vo = await ApplicationService.pass_application(db, application_id, remark=req.get("remark"))
    return R.success_resp(vo.model_dump(), msg="审核通过")


@router.post("/api/applications/{application_id}/reject")
async def reject_application(
    application_id: int = Path(..., description="申请ID"),
    req: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """审核员 REJECT"""
    remark = req.get("remark", "")
    vo = await ApplicationService.reject_application(db, application_id, remark=remark)
    return R.success_resp(vo.model_dump(), msg="已驳回")


@router.post("/api/admin/applications/{application_id}/revoke")
async def revoke_application(
    application_id: int = Path(..., description="申请ID"),
    req: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """撤回已通过的申请"""
    remark = req.get("remark", "")
    result = await ApplicationService.revoke(db, application_id, remark=remark)
    return R.success_resp(result, msg="已撤回")


# ════════════════════════════════════════════════════════════════════════
# 审核员端：列表查询
# ════════════════════════════════════════════════════════════════════════

@router.get("/api/admin/applications/my-pending")
async def list_my_pending(
    req: Annotated[ApplicationQueryRequest, Query()],
    db: AsyncSession = Depends(get_db),
):
    """我的待审核列表"""
    page = await ApplicationService.list_pending_for_me(db, req)
    return R.query_resp(page.model_dump())


@router.get("/api/admin/applications/my-reviewed")
async def list_my_reviewed(
    req: Annotated[ApplicationQueryRequest, Query()],
    db: AsyncSession = Depends(get_db),
):
    """我的已审核列表"""
    page = await ApplicationService.list_my_reviewed(db, req)
    return R.query_resp(page.model_dump())


__all__ = ["router"]
