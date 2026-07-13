"""score_data 路由（v4.3）

═══════════════════════════════════════════════════════════════════════
路由清单
═══════════════════════════════════════════════════════════════════════
学生端:
  GET  /api/score/me                  拉自己的分数树（命中或兜底 recalculate）
  POST /api/score/recalculate          手动触发重算，返回分数树

管理员端:
  POST /api/score/recalculate-all          批量重算（遍历所有学生）
  POST /api/score/recalculate-by-admin     单用户重算（?user_id=N）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.app.deps import get_db
from src.app.context import get_user_id
from src.app import response as R

from src.services import ScoreDataService
from src.models import User


router = APIRouter(prefix="/api/score", tags=["成绩"])


# ════════════════════════════════════════════════════════════════════════
# 学生端
# ════════════════════════════════════════════════════════════════════════
@router.get("/me")
async def get_my_score(
    db: AsyncSession = Depends(get_db),
):
    """拉自己的分数树（未命中则兜底 recalculate）

    v4.3 返回结构:
    {
        "calculated_at": "2026-07-08T...",
        "total": 60.0,
        "tree": [{id, name, max, score, raw, depth, isLeaf, applications, children}, ...]
    }
    """
    user_id = get_user_id()
    if not user_id:
        return R.unauthorized_resp("未登录")

    result = await ScoreDataService.get_summary(db, user_id)
    return R.query_resp(result)


@router.post("/recalculate")
async def recalculate_self(
    db: AsyncSession = Depends(get_db),
):
    """学生手动触发重算，返回分数树"""
    user_id = get_user_id()
    if not user_id:
        return R.unauthorized_resp("未登录")

    result = await ScoreDataService.recalculate(db, user_id)
    return R.success_resp(result, msg="成绩已重新计算")


# ════════════════════════════════════════════════════════════════════════
# 管理端
# ════════════════════════════════════════════════════════════════════════
@router.post("/recalculate-by-admin")
async def recalculate_by_admin(
    user_id: int = Query(..., description="目标学生 user_id"),
    db: AsyncSession = Depends(get_db),
):
    """管理员：单用户重算"""
    result = await ScoreDataService.recalculate(db, user_id)
    return R.success_resp({
        "userId": user_id,
        "score_info": result,   # flat 结构写 DB；tree 仅返回给前端
    }, msg="成绩已重新计算")


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
    }, msg=f"已重算 {len(user_ids)} 名学生")
