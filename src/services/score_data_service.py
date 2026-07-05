"""分数流水服务（v4.2）

═══════════════════════════════════════════════════════════════════════
三个核心方法
═══════════════════════════════════════════════════════════════════════
1. record() —— application.pass_application 同事务调用，写 score_data 行
2. recalculate() —— 学生 / 管理员按需触发，全量聚合叶子分类 → 封顶 → 写 user.score_info
3. get_summary() —— 学生端只读展示 user.score_info；未命中则兜底 recalculate

═══════════════════════════════════════════════════════════════════════
关键设计
═══════════════════════════════════════════════════════════════════════
- record 与 pass_application 同事务（atomic）
- recalculate 是幂等可反复触发的（全量覆盖）
- 聚合算法：3 条 SQL（叶子聚合 + 分类树 + UPDATE），O(1) 复杂度
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    ScoreData,
    TemplateCategory,
    User,
)


class ScoreDataService:
    """分数流水服务"""

    # ------------------------------------------------------------------
    # 1. record —— application.pass_application 同事务调用
    # ------------------------------------------------------------------
    @staticmethod
    async def record(
        db: AsyncSession,
        user_id: int,
        application_id: int,
        category_id: Optional[int],
        name: str,
        score: Decimal,
    ) -> ScoreData:
        """写入一条流水（v4.2）

        输入:
          - user_id: 学生 id
          - application_id: 已 PASSED 的 application
          - category_id: application.category_id（叶子分类）；可为 None（迁移期）
          - name: application.template_name 快照
          - score: application.apply_score（不是 gain_score）

        行为:
          - INSERT score_data (..., is_active=TRUE)
          - 不触发 recalculate（v4.2 决策——解耦到独立接口）

        事务: 与 pass_application 同事务（atomic）
        """
        if category_id is None:
            raise ValueError(
                "category_id 不能为 None（application 必须挂叶子分类）"
            )

        score_data = ScoreData(
            user_id=user_id,
            application_id=application_id,
            category_id=category_id,
            name=name,
            score=score,
            is_active=True,
        )
        db.add(score_data)
        await db.flush()
        return score_data

    # ------------------------------------------------------------------
    # 2. recalculate —— 全量聚合 + 写 user.score_info
    # ------------------------------------------------------------------
    @staticmethod
    async def recalculate(
        db: AsyncSession,
        user_id: int,
    ) -> Dict[str, Any]:
        """全量聚合 + 覆盖写 user.score_info

        算法（4 步）：
          Step 1: SQL 聚合叶子分类原始分
            SELECT category_id, SUM(score)
            FROM score_data
            WHERE user_id = :uid AND is_active = TRUE
            GROUP BY category_id

          Step 2: 内存组装 template_category 树
            SELECT * FROM template_category WHERE is_active = TRUE
            按 parent_id 建树，O(n) 一次遍历

          Step 3: 后序递归封顶
            叶子:   capped = min(raw, category.max_score)
            非叶:   capped = min(sum(子节点 capped), category.max_score)

          Step 4: 收集所有节点得分，覆盖写入 user.score_info
            UPDATE users SET score_info = :result WHERE id = :uid

        性能: 3 条 SQL（聚合 + 分类树 + UPDATE users），全过程内存递归
        """
        # Step 1: 叶子分类聚合
        result = await db.execute(
            select(
                ScoreData.category_id,
                func.sum(ScoreData.score).label("raw_sum"),
            )
            .where(
                and_(
                    ScoreData.user_id == user_id,
                    ScoreData.is_active == True,  # noqa: E712
                )
            )
            .group_by(ScoreData.category_id)
        )
        leaf_scores: Dict[int, Decimal] = {
            row.category_id: row.raw_sum for row in result
        }

        # Step 2: 加载分类树
        result = await db.execute(
            select(TemplateCategory).where(TemplateCategory.is_active == True)  # noqa: E712
        )
        all_categories = list(result.scalars().all())
        # 先取出所有字段值（避免后续访问触发 lazy load）
        cat_data = []
        for c in all_categories:
            cat_data.append({
                "id": c.id,
                "name": c.name,
                "parent_id": c.parent_id,
                "max_score": c.max_score,
            })

        # 用 dict 组装 children 关系（不依赖 ORM relationship 的 lazy load）
        node_map: Dict[int, Dict[str, Any]] = {
            d["id"]: {**d, "children": []} for d in cat_data
        }
        for d in cat_data:
            if d["parent_id"] and d["parent_id"] in node_map:
                node_map[d["parent_id"]]["children"].append(node_map[d["id"]])
        roots = [node_map[d["id"]] for d in cat_data if not d["parent_id"]]

        # Step 3: 后序递归封顶
        # 先算出每个节点的封顶分数（用于 categories_result）
        score_map: Dict[int, Decimal] = {}

        def calc(node: Dict[str, Any]) -> Decimal:
            if not node["children"]:
                raw = leaf_scores.get(node["id"], Decimal("0"))
                capped = min(raw, Decimal(str(node["max_score"]))) if node["max_score"] is not None else raw
            else:
                child_sum = sum(calc(child) for child in node["children"])
                capped = min(child_sum, Decimal(str(node["max_score"]))) if node["max_score"] is not None else child_sum
            score_map[node["id"]] = capped
            return capped

        for root in roots:
            calc(root)

        # Step 4: 收集所有节点得分（不只是根）
        categories_result: Dict[str, Dict[str, Any]] = {}
        total_score = Decimal("0")
        for d in cat_data:
            score = score_map.get(d["id"], Decimal("0"))
            categories_result[str(d["id"])] = {
                "name": d["name"],
                "score": float(score),
                "max": float(d["max_score"]) if d["max_score"] is not None else None,
            }
            if d["parent_id"] is None:
                total_score = score

        # Step 4: 写 user.score_info
        user = await db.get(User, user_id)
        if not user:
            raise ValueError(f"用户(id={user_id})不存在")

        result_dict = {
            "calculated_at": datetime.utcnow().isoformat() + "Z",
            "categories": categories_result,
            "total": float(total_score),
        }
        user.score_info = result_dict

        await db.commit()
        await db.refresh(user)
        return result_dict

    # ------------------------------------------------------------------
    # 3. get_summary —— 学生端只读展示
    # ------------------------------------------------------------------
    @staticmethod
    async def get_summary(
        db: AsyncSession,
        user_id: int,
    ) -> Dict[str, Any]:
        """读取 user.score_info 快照，不重算。

        返回:
          - 命中: {"hit": True, "score_info": {...}}
          - 未命中: 触发一次 recalculate（兜底），返回计算后的 score_info
        """
        user = await db.get(User, user_id)
        if not user:
            return {"hit": False, "score_info": {}}

        score_info = user.score_info or {}
        if score_info and isinstance(score_info, dict) and score_info.get("categories"):
            return {"hit": True, "score_info": score_info}

        # 兜底重算
        score_info = await ScoreDataService.recalculate(db, user_id)
        return {"hit": False, "score_info": score_info}