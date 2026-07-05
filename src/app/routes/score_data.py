"""score_data 路由（v4.2）

═══════════════════════════════════════════════════════════════════════
路由清单
═══════════════════════════════════════════════════════════════════════
学生端:
  GET  /api/score/summary                  拉自己的分数快照（命中或兜底 recalculate）
  POST /api/score/recalculate              手动触发重算

管理员端:
  POST /api/score/recalculate-all          批量重算（遍历所有学生）
  POST /api/score/recalculate-by-admin     单用户重算（?user_id=N）
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from src.app.deps import get_db
from src.app.context import get_user_id
from src.app import response as R

from src.services import ScoreDataService
from src.models import User


router = APIRouter(prefix="/api/score", tags=["分数流水"])


# ════════════════════════════════════════════════════════════════════════
# 学生端
# ════════════════════════════════════════════════════════════════════════
@router.get("/summary")
async def get_summary(
    db: AsyncSession = Depends(get_db),
):
    """拉自己的分数快照（未命中则兜底 recalculate）"""
    user_id = get_user_id()
    if not user_id:
        return R.unauthorized_resp("未登录")

    result = await ScoreDataService.get_summary(db, user_id)
    return R.success_resp(result)


@router.post("/recalculate")
async def recalculate_self(
    db: AsyncSession = Depends(get_db),
):
    """学生手动触发重算"""
    user_id = get_user_id()
    if not user_id:
        return R.unauthorized_resp("未登录")

    score_info = await ScoreDataService.recalculate(db, user_id)
    return R.success_resp({
        "hit": True,
        "score_info": score_info,
    })


# ════════════════════════════════════════════════════════════════════════
# 管理端
# ════════════════════════════════════════════════════════════════════════
@router.post("/recalculate-by-admin")
async def recalculate_by_admin(
    user_id: int = Query(..., description="目标学生 user_id"),
    db: AsyncSession = Depends(get_db),
):
    """管理员：单用户重算"""
    score_info = await ScoreDataService.recalculate(db, user_id)
    return R.success_resp({
        "userId": user_id,
        "score_info": score_info,
    })


@router.post("/recalculate-all")
async def recalculate_all(
    db: AsyncSession = Depends(get_db),
):
    """管理员：批量重算（遍历所有学生）

    返回:
      - total: 学生总数
      - success: 成功数
      - errors: 失败列表 [{user_id, error}, ...]
    """
    result = await db.execute(select(User.id))
    user_ids = [row[0] for row in result.all()]

    success = 0
    errors = []
    for uid in user_ids:
        try:
            await ScoreDataService.recalculate(db, uid)
            success += 1
        except Exception as e:
            errors.append({"user_id": uid, "error": str(e)})

    return R.success_resp({
        "total": len(user_ids),
        "success": success,
        "errors": errors,
    })