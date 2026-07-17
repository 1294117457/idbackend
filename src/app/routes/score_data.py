"""score_data 路由（v4.6）

═══════════════════════════════════════════════════════════════════════
路由清单
═══════════════════════════════════════════════════════════════════════
学生端:
  GET  /api/score/me                  只读：内存拼装分数树（不重算）
  GET  /api/score/applications        按 category_id 拉该学生该分类下的 applications
  POST /api/score/recalculate         手动触发重算，返回分数树

管理员端:
  POST /api/score/recalculate-by-admin    单用户重算（?user_id=N）
  POST /api/score/recalculate-all         批量重算（遍历所有学生）

═══════════════════════════════════════════════════════════════════════
v4.6 关键变更（基于 user-score.md v1.1）
═══════════════════════════════════════════════════════════════════════
- 拆分读写路径：
  * GET /me —— 只读，1 条 SELECT users + 1 条 SELECT template_category，内存组装 tree
  * POST /recalculate —— 写路径，3 条 SQL + 1 条 UPDATE users
- score_info 持久化字段精简为 { calculated_at, total, scores: { cat_id: { score, raw } } }
  * 不再持久化 tree 字段（派生数据）
  * 不再持久化 categories 字典（被 scores 替代）
  * 不再持久化 applications（事实数据，按需查询）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.app.dependencies import get_db
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
    """拉自己的分数树（只读，不触发重算）

    v4.6 行为：
      - 命中（user.score_info.scores 已存在） → 内存拼装 tree 返回
      - 未命中（从未算过） → 返回 empty=true，引导前端点"刷新成绩"

    返回结构:
      {
        "calculated_at": "2026-07-14T..." | null,
        "total": 60.0,
        "tree": [{id, name, max, score, raw, depth, isLeaf, applications, children}, ...],
        "empty": false   // true 表示从未算过
      }

    性能：2 条 SELECT（users.score_info + template_category），无 UPDATE
    """
    user_id = get_user_id()
    if not user_id:
        return R.unauthorized_resp("未登录")

    result = await ScoreDataService.get_summary(db, user_id)
    return R.query_resp(result)


@router.get("/applications")
async def get_my_applications(
    category_id: int = Query(..., description="叶子分类 ID"),
    db: AsyncSession = Depends(get_db),
):
    """按 category_id 拉该学生该分类下所有 active 的 application 流水。

    用途：前端点击分数树叶子节点时按需加载右侧 application 列表。

    返回:
      [
        {
          "id": int,            // application.id
          "name": str,          // 模板名快照
          "score": float,
          "created_at": str,    // ISO datetime
        },
        ...
      ]
    按 created_at DESC 排序。

    性能：1 条 SELECT（命中 idx_score_data_user_category 复合索引）
    """
    user_id = get_user_id()
    if not user_id:
        return R.unauthorized_resp("未登录")

    result = await ScoreDataService.get_applications_by_category(
        db, user_id=user_id, category_id=category_id,
    )
    return R.query_resp(result)


@router.post("/recalculate")
async def recalculate_self(
    db: AsyncSession = Depends(get_db),
):
    """学生手动触发重算，返回分数树

    返回结构同 GET /me（extra：tree 是 recalculate 现场组装的最新树）

    性能：3 条 SQL（聚合 + 分类树 + 1×UPDATE users）
    """
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
        "score_info": result,
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