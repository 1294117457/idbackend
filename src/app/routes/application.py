"""申请路由

职责：只做接收接口数据、传递给 service、返回对应数据。
认证、contextvar 操作、异常处理由中间件统一处理。

路由设计（统一 action-style）：
  - POST /api/applications              → 统一接口（action: save/submit/edit）
  - POST /api/applications/review       → 审核接口（action: pass/reject）
  - POST /api/applications/cancel       → 取消申请
  - POST /api/admin/applications/revoke → 撤回申请
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query, Body
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
# 学生端：统一申请接口
# ════════════════════════════════════════════════════════════════════════

@router.post("/api/applications", status_code=201)
async def handle_application(
    req: ApplicationPayload,
    db: AsyncSession = Depends(get_db),
):
    """统一申请接口（save/submit/edit）"""
    action = req.action
    if action == "save":
        vo = await ApplicationService.save_draft(db, req)
        return R.created_resp(vo.model_dump(), msg="草稿保存成功")
    elif action == "submit":
        vo = await ApplicationService.submit(db, req)
        return R.created_resp(vo.model_dump(), msg="申请已提交")
    elif action == "edit":
        vo = await ApplicationService.edit_submit(db, req)
        return R.created_resp(vo.model_dump(), msg="申请已提交")
    else:
        from src.app.schemas.errors import BadRequestError
        raise BadRequestError(f"action 必须为 save/submit/edit，当前：{action}")


@router.post("/api/applications/cancel")
async def cancel_application(
    req: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """取消申请"""
    application_id = req.get("id") or req.get("applicationId")
    remark = req.get("remark")
    vo = await ApplicationService.cancel(db, application_id, remark=remark)
    return R.success_resp(vo.model_dump(), msg="申请已取消")


@router.post("/api/applications/touch")
async def touch_application(
    req: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """DRAFT 状态下纯刷 updated_at"""
    application_id = req.get("id") or req.get("applicationId")
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


@router.get("/api/applications/detail")
async def get_application_detail(
    id: int = Query(..., ge=1, description="申请ID"),
    db: AsyncSession = Depends(get_db),
):
    """申请详情（含 proofs + operations）"""
    vo = await ApplicationService.get_detail(db, id)
    return R.query_resp(vo.model_dump())


# ════════════════════════════════════════════════════════════════════════
# 审核员端：审核 / 投票
# ════════════════════════════════════════════════════════════════════════

@router.post("/api/applications/review")
async def review_application(
    req: ApplicationPayload = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """审核员投票（pass/reject，统一 Payload + action）"""
    if req.reviewAction == "pass":
        vo = await ApplicationService.pass_application(db, req)
        return R.success_resp(vo.model_dump(), msg="审核通过")
    elif req.reviewAction == "reject":
        vo = await ApplicationService.reject_application(db, req)
        return R.success_resp(vo.model_dump(), msg="已驳回")
    else:
        from src.app.schemas.errors import BadRequestError
        raise BadRequestError(f"reviewAction 必须为 pass/reject，当前：{req.reviewAction}")


@router.post("/api/admin/applications/revoke")
async def revoke_application(
    req: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """撤回已通过的申请"""
    application_id = req.get("id") or req.get("applicationId")
    remark = req.get("remark", "")
    result = await ApplicationService.revoke(db, application_id, remark=remark)
    return R.success_resp(result, msg="已撤回")


# ════════════════════════════════════════════════════════════════════════
# 审核员端：列表查询
# ════════════════════════════════════════════════════════════════════════

@router.get("/api/admin/applications/my-pending")
async def list_my_pending(
    req: ApplicationQueryRequest = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """我的待审核列表"""
    page = await ApplicationService.list_pending_for_me(db, req)
    return R.query_resp(page.model_dump())


@router.get("/api/admin/applications/my-reviewed")
async def list_my_reviewed(
    req: ApplicationQueryRequest = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """我的已审核列表"""
    page = await ApplicationService.list_my_reviewed(db, req)
    return R.query_resp(page.model_dump())


__all__ = ["router"]
