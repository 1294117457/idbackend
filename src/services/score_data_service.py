"""分数流水服务（v4.6）

═══════════════════════════════════════════════════════════════════════
四个核心方法
═══════════════════════════════════════════════════════════════════════
1. record()                —— application.pass_application 同事务调用，写 score_data 行
2. recalculate()           —— 学生 / 管理员按需触发，全量聚合叶子分类 → 封顶 → 写 user.score_info
3. get_summary()           —— 学生端只读展示：拼装 template_category + user.score_info 内存组树（不重算）
4. get_applications_by_category() —— 拉某叶子分类下该用户所有 active 的 score_data

═══════════════════════════════════════════════════════════════════════
v4.6 升级（基于 user-score.md v1.1，修复 v4.3 反模式）
═══════════════════════════════════════════════════════════════════════
- 拆分读写路径：
  * score_info 持久化字段精简为 { calculated_at, total, scores: { cat_id: { score, raw } } }
  * tree 是派生数据，**不写 DB**，由 get_summary 在内存里从 template_category + scores 组装
  * applications 是事实数据，**不写 DB**，由独立的 /score/applications 按需拉取
- 重写 get_summary 为只读路径：
  * 命中 → 内存组装 tree 返回
  * 未命中(从未算过) → 返回 empty=true，前端引导点"刷新"
  * 不再触发 recalculate（v4.3 反模式：/me 接口强制重算导致 1 次进页 = 1 次 UPDATE）
- recalculate 写回 score_info 时不再带 categories 字典和 tree 字段
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Dict, Any, List

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
        """全量聚合 + 覆盖写 user.score_info（v4.6 精简版）

        算法（v4.6）：
          Step 1: SQL 聚合叶子分类原始分（from score_data）
          Step 2: 加载 template_category 全表，内存组树
          Step 3: 后序递归封顶（算 raw + capped）
          Step 4: 再次后序递归（补算非叶 raw）
          Step 5: 写 user.score_info（精简结构：{calculated_at, total, scores}）

        v4.6 写回 score_info 的精简结构:
          {
            "calculated_at": "2026-07-14T...Z",
            "total": 60.0,
            "scores": {
              "2": {"score": 0.0, "raw": 0.0},   // 封顶分 + 原始分
              "3": {"score": 0.0, "raw": 0.0},
              ...
            }
          }

        接口返回值（供路由层直接返回）：
          {
            "calculated_at": "...",
            "total": 60.0,
            "tree": [...]   // 派生：内存组装的展示树（与 score_info 中一致）
          }

        性能：3 条 SQL（聚合 + 分类树 + 1×UPDATE users）
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

        # Step 2: 加载分类树
        result = await db.execute(
            select(TemplateCategory).where(
                and_(
                    TemplateCategory.is_active == True,  # noqa: E712
                    TemplateCategory.is_deleted == False,  # noqa: E712
                )
            ).order_by(
                TemplateCategory.parent_id.nulls_first(),
                TemplateCategory.sort_order.asc(),
                TemplateCategory.id.asc(),
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
                "sort_order": c.sort_order,
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

        # total = 所有根节点封顶后 score 之和
        total_score_val = sum(node_score.get(root["id"], Decimal("0")) for root in roots)
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        # Step 5: 写 user.score_info（v4.6 精简结构：去掉 categories 字典 + tree 字段）
        user = await db.get(User, user_id)
        if not user:
            raise ValueError(f"用户(id={user_id})不存在")

        scores_dict: Dict[str, Dict[str, float]] = {}
        for d in cat_data:
            cat_id = d["id"]
            scores_dict[str(cat_id)] = {
                "score": float(node_score.get(cat_id, Decimal("0"))),
                "raw": float(node_raw.get(cat_id, Decimal("0"))),
            }

        db_result_dict = {
            "calculated_at": now_iso,
            "total": float(total_score_val),
            "scores": scores_dict,
        }
        user.score_info = db_result_dict

        await db.commit()
        await db.refresh(user)

        # 接口返回：精简字段 + 内存组装的展示树（前端 /score 页面用）
        tree = ScoreDataService._build_tree(roots, scores_dict, include_applications=False)

        return {
            "calculated_at": now_iso,
            "total": float(total_score_val),
            "tree": tree,
        }

    # ------------------------------------------------------------------
    # 3. get_summary —— 学生端只读展示（v4.6：纯读路径，不触发 recalculate）
    # ------------------------------------------------------------------
    @staticmethod
    async def get_summary(
        db: AsyncSession,
        user_id: int,
    ) -> Dict[str, Any]:
        """只读：拼装 template_category + user.score_info 返回展示树。

        v4.6 行为：
          - 命中（score_info 已有 scores 字段）：
              * 1 条 SELECT users
              * 1 条 SELECT template_category
              * 内存组装 tree 返回
              * 不触发 UPDATE
          - 未命中（从未算过）：
              * 1 条 SELECT users
              * 1 条 SELECT template_category
              * 返回全 0 分的框架树 + empty=true
              * 前端展示模板结构，引导用户点"计算成绩"

        返回结构:
          {
            "calculated_at": "..." | null,
            "total": float,
            "tree": [...],
            "empty": bool,   // true 表示从未算过，前端引导刷新
          }
        """
        user = await db.get(User, user_id)
        if not user:
            return {
                "calculated_at": None,
                "total": 0.0,
                "tree": [],
                "empty": True,
            }

        score_info = user.score_info or {}
        scores_dict = score_info.get("scores")

        # 模板全表加载（命中/未命中都用），统一组装框架
        roots = await ScoreDataService._load_category_roots(db)

        if not scores_dict or not isinstance(scores_dict, dict):
            # 从没算过：返回全 0 分的框架树，让前端展示分类结构
            empty_scores: Dict[str, Dict[str, float]] = {
                str(root["id"]): {"score": 0.0, "raw": 0.0}
                for root in roots
            }
            tree = ScoreDataService._build_tree(roots, empty_scores, include_applications=False)
            return {
                "calculated_at": None,
                "total": 0.0,
                "tree": tree,
                "empty": True,
            }

        # 命中：内存组装 tree
        tree = ScoreDataService._build_tree(roots, scores_dict, include_applications=False)

        return {
            "calculated_at": score_info.get("calculated_at"),
            "total": float(score_info.get("total", 0.0)),
            "tree": tree,
            "empty": False,
        }

    # ------------------------------------------------------------------
    # 4. get_applications_by_category —— 按 category_id 拉 applications
    # ------------------------------------------------------------------
    @staticmethod
    async def get_applications_by_category(
        db: AsyncSession,
        user_id: int,
        category_id: int,
    ) -> List[Dict[str, Any]]:
        """按 user_id + category_id 拉该学生该分类下所有 active 的 score_data 记录。

        用于前端点击分类树的叶子节点时按需加载 application 列表。

        返回:
          [
            {
              "id": int,            // application.id（也是 score_data.application_id）
              "name": str,          // 模板名快照
              "score": float,       // 该条流水贡献的分数
              "created_at": str,    // ISO datetime，通过时间
            },
            ...
          ]
        按 created_at DESC 排序（最新在前）。
        """
        result = await db.execute(
            select(ScoreData).where(
                and_(
                    ScoreData.user_id == user_id,
                    ScoreData.category_id == category_id,
                    ScoreData.is_active == True,  # noqa: E712
                )
            ).order_by(ScoreData.created_at.desc())
        )
        rows = list(result.scalars().all())
        return [
            {
                "id": r.application_id,
                "name": r.name or "",
                "score": float(r.score),
                "created_at": r.created_at.isoformat() if r.created_at else "",
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # 内部工具 —— 模板加载与组树（无 DB 写）
    # ------------------------------------------------------------------
    @staticmethod
    async def _load_category_roots(db: AsyncSession) -> List[Dict[str, Any]]:
        """加载全量激活的 template_category，组装 children，返回根节点列表（Python dict）。

        用途：recalculate 写 score_info 后拼装展示树、get_summary 只读拼装树。
        """
        result = await db.execute(
            select(TemplateCategory).where(
                and_(
                    TemplateCategory.is_active == True,  # noqa: E712
                    TemplateCategory.is_deleted == False,  # noqa: E712
                )
            ).order_by(
                TemplateCategory.parent_id.nulls_first(),
                TemplateCategory.sort_order.asc(),
                TemplateCategory.id.asc(),
            )
        )
        all_categories = list(result.scalars().all())
        cat_data = [
            {
                "id": c.id,
                "name": c.name,
                "parent_id": c.parent_id,
                "max_score": c.max_score,
                "is_bind_template": c.is_bind_template,
                "sort_order": c.sort_order,
            }
            for c in all_categories
        ]

        node_map: Dict[int, Dict[str, Any]] = {
            d["id"]: {**d, "children": []} for d in cat_data
        }
        for d in cat_data:
            if d["parent_id"] and d["parent_id"] in node_map:
                node_map[d["parent_id"]]["children"].append(node_map[d["id"]])
        roots = [node_map[d["id"]] for d in cat_data if not d["parent_id"]]
        return roots

    @staticmethod
    def _build_tree(
        roots: List[Dict[str, Any]],
        scores_dict: Dict[str, Dict[str, float]],
        *,
        include_applications: bool = False,
        apps_by_cat: Optional[Dict[int, List[Dict[str, Any]]]] = None,
    ) -> List[Dict[str, Any]]:
        """从模板根节点 + scores 字典，递归组展示树。

        节点结构:
          {
            "id": int,
            "name": str,
            "max": float,
            "score": float,
            "raw": float,
            "depth": int,
            "isLeaf": bool,
            "applications": [...],   // 仅 include_applications=True 时填充
            "children": [...],
          }
        """
        def walk(node: Dict[str, Any], depth: int) -> Dict[str, Any]:
            cat_id = node["id"]
            s = scores_dict.get(str(cat_id), {"score": 0.0, "raw": 0.0})
            entry: Dict[str, Any] = {
                "id": cat_id,
                "name": node["name"],
                "max": float(node["max_score"]) if node["max_score"] is not None else 0.0,
                "score": float(s.get("score", 0.0)),
                "raw": float(s.get("raw", 0.0)),
                "depth": depth,
                "isLeaf": bool(node.get("is_bind_template", False)),
                "children": [
                    walk(child, depth + 1)
                    for child in sorted(
                        node["children"],
                        key=lambda c: (c.get("sort_order", 0), c["id"]),
                    )
                ],
            }
            if include_applications and apps_by_cat is not None:
                entry["applications"] = apps_by_cat.get(cat_id, [])
            else:
                entry["applications"] = []
            return entry

        return [walk(r, 0) for r in roots]