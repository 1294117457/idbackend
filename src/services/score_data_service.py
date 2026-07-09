"""分数流水服务（v4.3）

═══════════════════════════════════════════════════════════════════════
三个核心方法
═══════════════════════════════════════════════════════════════════════
1. record() —— application.pass_application 同事务调用，写 score_data 行
2. recalculate() —— 学生 / 管理员按需触发，全量聚合叶子分类 → 封顶 → 写 user.score_info
3. get_summary() —— 学生端只读展示；未命中则兜底 recalculate

═══════════════════════════════════════════════════════════════════════
v4.3 升级（user-score.md v1.1）
═══════════════════════════════════════════════════════════════════════
- recalculate / get_summary 新增返回 tree 结构（用于学生端"我的成绩"卡片）
- tree 字段不写 DB，只作为接口返回的派生字段
- SQL 总量仍为 5 条（新增 1 条拉 application 列表）
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Dict, Any, List

from sqlalchemy import select, func, and_, text
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

        算法（7 步，v4.3 新增 tree 返回）：
          Step 1: SQL 聚合叶子分类原始分（from score_data）
          Step 2: 内存组装 template_category 树
          Step 3: 后序递归封顶（首遍：算 raw + capped）
          Step 4: 再次后序递归（补算非叶 raw）
          Step 5: SQL 拉 application 列表按 category_id 分组
          Step 6: 组装 tree 结构（id/name/max/score/raw/depth/isLeaf/applications/children）
          Step 7: 写 user.score_info（旧 flat 结构）

        性能: 5 条 SQL（聚合 + 分类树 + application 列表 + 2×UPDATE users）
        """
        # Step 1: 叶子分类原始分聚合
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

        # Step 2: 加载分类树（含 is_bind_template，用于判断 isLeaf）
        # 过滤 is_active=True 且 is_deleted=False（排除软删除的分类）
        result = await db.execute(
            select(TemplateCategory).where(
                and_(
                    TemplateCategory.is_active == True,  # noqa: E712
                    TemplateCategory.is_deleted == False,  # noqa: E712
                )
            )
        )
        all_categories = list(result.scalars().all())
        cat_data = []
        for c in all_categories:
            cat_data.append({
                "id": c.id,
                "name": c.name,
                "parent_id": c.parent_id,
                "max_score": c.max_score,
                "is_bind_template": c.is_bind_template,
            })

        # 用 dict 组装 children 关系
        node_map: Dict[int, Dict[str, Any]] = {
            d["id"]: {**d, "children": []} for d in cat_data
        }
        for d in cat_data:
            if d["parent_id"] and d["parent_id"] in node_map:
                node_map[d["parent_id"]]["children"].append(node_map[d["id"]])
        roots = [node_map[d["id"]] for d in cat_data if not d["parent_id"]]

        # Step 3: 后序递归封顶（首遍：算 raw + capped）
        node_raw: Dict[int, Decimal] = {}
        node_score: Dict[int, Decimal] = {}

        def calc_first_pass(node: Dict[str, Any]) -> Decimal:
            if not node["children"]:
                raw = leaf_scores.get(node["id"], Decimal("0"))
            else:
                raw = sum(calc_first_pass(child) for child in node["children"])
            max_val = Decimal(str(node["max_score"])) if node["max_score"] is not None else None
            capped = min(raw, max_val) if max_val is not None else raw
            node_raw[node["id"]] = raw
            node_score[node["id"]] = capped
            return capped

        for root in roots:
            calc_first_pass(root)

        # Step 4: 再次后序，把非叶子的 raw 补算为子节点 score 之和（用于前端展示"超额"）
        def calc_raw_from_children(node: Dict[str, Any]) -> Decimal:
            if not node["children"]:
                return node_raw.get(node["id"], Decimal("0"))
            s = sum(calc_raw_from_children(child) for child in node["children"])
            node_raw[node["id"]] = s
            return s

        for root in roots:
            calc_raw_from_children(root)

        # Step 5: SQL 拉 application 列表按 category_id 分组
        app_result = await db.execute(
            text("""
                SELECT application_id, category_id, name, score, created_at
                FROM score_data
                WHERE user_id = :uid AND is_active = TRUE
                ORDER BY category_id, created_at DESC
            """),
            {"uid": user_id},
        )
        apps_by_cat: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for r in app_result:
            apps_by_cat[r.category_id].append({
                "id": r.application_id,
                "name": r.name,
                "score": float(r.score),
                "created_at": r.created_at.isoformat() if r.created_at else "",
            })

        # Step 6: 组装 tree（递归建树，返回结构化节点）
        def build_tree(node: Dict[str, Any], depth: int) -> Dict[str, Any]:
            cat_id = node["id"]
            return {
                "id": cat_id,
                "name": node["name"],
                "max": float(node["max_score"]) if node["max_score"] is not None else 0.0,
                "score": float(node_score.get(cat_id, Decimal("0"))),
                "raw": float(node_raw.get(cat_id, Decimal("0"))),
                "depth": depth,
                "isLeaf": bool(node.get("is_bind_template", False)),
                "applications": apps_by_cat.get(cat_id, []),
                "children": [
                    build_tree(child, depth + 1)
                    for child in sorted(node["children"], key=lambda c: (c.get("sort_order", 0), c["id"]))
                ],
            }

        tree = [build_tree(root, 0) for root in roots]

        # total = 所有根节点封顶后 score 之和
        total_score_val = sum(node_score.get(root["id"], Decimal("0")) for root in roots)
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        # Step 7: 写 user.score_info（含 flat categories + tree，供 profile 接口直接返回）
        user = await db.get(User, user_id)
        if not user:
            raise ValueError(f"用户(id={user_id})不存在")

        # 构造 flat categories_result（用于写 DB）
        categories_result: Dict[str, Dict[str, Any]] = {}
        for d in cat_data:
            cat_id = d["id"]
            categories_result[str(cat_id)] = {
                "name": d["name"],
                "score": float(node_score.get(cat_id, Decimal("0"))),
                "max": float(d["max_score"]) if d["max_score"] is not None else None,
            }

        db_result_dict = {
            "calculated_at": now_iso,
            "categories": categories_result,
            "total": float(total_score_val),
            "tree": tree,
        }
        user.score_info = db_result_dict

        await db.commit()
        await db.refresh(user)

        # 接口返回：flat 结构 + tree 派生字段
        return {
            "calculated_at": now_iso,
            "total": float(total_score_val),
            "tree": tree,
        }

    # ------------------------------------------------------------------
    # 3. get_summary —— 学生端只读展示
    # ------------------------------------------------------------------
    @staticmethod
    async def get_summary(
        db: AsyncSession,
        user_id: int,
    ) -> Dict[str, Any]:
        """读取 user.score_info 快照，不重算。

        v4.3 返回结构升级：直接返回 recalculate 的 tree 结构，
        不再包一层 {"hit": ..., "score_info": ...}。

        返回:
          - 命中: 直接返回 score_info（含 tree 字段）
          - 未命中: 触发一次 recalculate，返回计算后的结果（含 tree）
        """
        user = await db.get(User, user_id)
        if not user:
            return {}

        score_info = user.score_info or {}
        if score_info and isinstance(score_info, dict) and score_info.get("categories"):
            # 命中：直接返回（不含 tree，需要前端再调 recalculate 或后端补 tree）
            # v4.3 策略：命中时也触发一次 recalculate，保证返回完整 tree
            result = await ScoreDataService.recalculate(db, user_id)
            return result

        # 未命中：兜底重算
        result = await ScoreDataService.recalculate(db, user_id)
        return result
