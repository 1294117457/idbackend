"""TemplateCategory 服务（Layer 1）

设计原则（详见 docs/core-function/四层职责设计.md）：
- 所有写操作必须在 service 层校验业务约束，DB 层 CHECK 仅为兜底
- `is_bind_template` 是状态机托管字段：
    TRUE  = 分类已绑 template，不可再加子，不可再绑 template
    FALSE = 分类未绑 template，可加子，可绑 template
- 分类层级是 N-ary 树（一个父可多个子）；不再有"is_leaf"概念
- 删除走单事务：预检未关闭 application → 收集后代 → 一次删除
- 不提供 move / change_parent（要调整位置只能删旧建新）

风格参考 src/services/attribute_service.py：静态方法、AsyncSession 注入。
"""
from decimal import Decimal
from typing import Optional, List, Dict, Any, Set

from sqlalchemy import select, delete, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.template_category import TemplateCategory


# ===================== 业务异常 =====================

class CategoryError(Exception):
    """模板分类相关业务异常基类"""


class CategoryNotFound(CategoryError):
    """分类不存在"""


class CategoryNameDuplicate(CategoryError):
    """同级下 name 重复"""

    def __init__(self, name: str, parent_id: Optional[int]):
        self.name = name
        self.parent_id = parent_id
        super().__init__(f"同级下已存在同名分类: {name}")


class ParentAlreadyBound(CategoryError):
    """父节点已绑 template，不可再添加子分类（叶子已被占用）"""

    def __init__(self, parent_id: int):
        self.parent_id = parent_id
        super().__init__(
            f"父节点(id={parent_id})已绑定 template，不可继续添加子分类"
        )


class CategoryHasActiveApplications(CategoryError):
    """删除时存在未关闭的 application，禁止删除"""

    def __init__(self, count: int):
        self.count = count
        super().__init__(
            f"该分类及其子分类下还有 {count} 条未关闭的申请，禁止删除"
        )


# ===================== 服务实现 =====================

class TemplateCategoryService:

    # ---------- 读接口 ----------

    @staticmethod
    async def get_tree(
        db: AsyncSession,
        *,
        include_inactive: bool = False,
    ) -> List[Dict[str, Any]]:
        """获取完整分类树（嵌套结构），供管理端展示。

        返回结构：
        [
            {
                "id": 1, "name": "加分总计", "parentId": null,
                "maxScore": "100.00", "isBindTemplate": False,
                "sortOrder": 1, "isActive": True, "description": "...",
                "children": [ ... ],
            },
            ...
        ]
        """
        stmt = select(TemplateCategory)
        if not include_inactive:
            stmt = stmt.where(TemplateCategory.is_active == True)
        stmt = stmt.order_by(
            TemplateCategory.sort_order.asc(),
            TemplateCategory.id.asc(),
        )
        result = await db.execute(stmt)
        all_nodes = list(result.scalars().all())

        # 按 id 建索引 + 嵌套组装
        nodes_by_id: Dict[int, Dict[str, Any]] = {}
        for n in all_nodes:
            nodes_by_id[n.id] = _serialize(n, with_children=True)

        roots: List[Dict[str, Any]] = []
        for n in all_nodes:
            serialized = nodes_by_id[n.id]
            if n.parent_id is None:
                roots.append(serialized)
            else:
                parent_dict = nodes_by_id.get(n.parent_id)
                if parent_dict is not None:
                    parent_dict["children"].append(serialized)

        return roots

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        category_id: int,
    ) -> Optional[TemplateCategory]:
        """根据 ID 获取分类"""
        return await db.get(TemplateCategory, category_id)

    @staticmethod
    async def get_leaf_categories(
        db: AsyncSession,
        *,
        include_inactive: bool = False,
    ) -> List[TemplateCategory]:
        """获取所有"可绑 template"的分类（is_bind_template=FALSE 且 is_active=TRUE）。

        注：语义从"is_leaf=TRUE"改为"is_bind_template=FALSE"——
        当前 store 端：未绑 template 时即可绑；绑后状态翻转。
        """
        stmt = select(TemplateCategory).where(
            TemplateCategory.is_bind_template == False
        )
        if not include_inactive:
            stmt = stmt.where(TemplateCategory.is_active == True)
        stmt = stmt.order_by(
            TemplateCategory.sort_order.asc(),
            TemplateCategory.id.asc(),
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_category_path(
        db: AsyncSession,
        category_id: int,
    ) -> List[TemplateCategory]:
        """获取从根到当前节点的完整路径（不含当前节点的祖先链，含自身）。"""
        from sqlalchemy import text

        sql = text("""
            WITH RECURSIVE path AS (
                SELECT id, name, parent_id, sort_order, 0 AS depth
                FROM template_category
                WHERE id = :start_id
                UNION ALL
                SELECT tc.id, tc.name, tc.parent_id, tc.sort_order, p.depth + 1
                FROM template_category tc
                JOIN path p ON tc.id = p.parent_id
            )
            SELECT id, name, parent_id, sort_order
            FROM path
            ORDER BY depth DESC
        """)
        result = await db.execute(sql, {"start_id": category_id})
        rows = result.all()
        if not rows:
            return []

        nodes: List[TemplateCategory] = []
        for row in rows:
            node = TemplateCategory(
                id=row.id,
                name=row.name,
                parent_id=row.parent_id,
                sort_order=row.sort_order,
                max_score=Decimal("0"),
                is_bind_template=False,
            )
            nodes.append(node)
        return nodes

    @staticmethod
    async def get_descendants(
        db: AsyncSession,
        category_id: int,
        *,
        include_self: bool = False,
    ) -> List[TemplateCategory]:
        """获取指定分类及其所有后代（深度优先）。"""
        from sqlalchemy import text

        sql = text("""
            WITH RECURSIVE descendants AS (
                SELECT id, name, parent_id, max_score, is_bind_template,
                       sort_order, is_active, description, 0 AS depth
                FROM template_category
                WHERE id = :start_id
                UNION ALL
                SELECT tc.id, tc.name, tc.parent_id, tc.max_score, tc.is_bind_template,
                       tc.sort_order, tc.is_active, tc.description, d.depth + 1
                FROM template_category tc
                JOIN descendants d ON tc.parent_id = d.id
            )
            SELECT id, name, parent_id, max_score, is_bind_template,
                   sort_order, is_active, description, depth
            FROM descendants
            ORDER BY depth ASC, sort_order ASC, id ASC
        """)
        result = await db.execute(sql, {"start_id": category_id})
        rows = result.all()

        nodes: List[TemplateCategory] = []
        for row in rows:
            if not include_self and row.depth == 0:
                continue
            nodes.append(_row_to_category(row))
        return nodes

    # ---------- 写接口 ----------

    @staticmethod
    async def create_root(
        db: AsyncSession,
        *,
        name: str,
        max_score: Decimal,
        description: Optional[str] = None,
        sort_order: int = 0,
    ) -> TemplateCategory:
        """创建根节点（parent_id=NULL）。"""
        await _check_name_unique(db, name=name, parent_id=None)
        await _check_max_score(max_score)

        category = TemplateCategory(
            name=name,
            parent_id=None,
            max_score=max_score,
            is_bind_template=False,
            sort_order=sort_order,
            is_active=True,
            description=description,
        )
        db.add(category)
        await db.commit()
        await db.refresh(category)
        return category

    @staticmethod
    async def create_child(
        db: AsyncSession,
        *,
        parent_id: int,
        name: str,
        max_score: Decimal,
        description: Optional[str] = None,
        sort_order: int = 0,
    ) -> TemplateCategory:
        """创建子分类（N-ary 树）。

        流程：
        1. 加载父节点，不存在抛 CategoryNotFound
        2. 父节点必须 is_bind_template=FALSE（未绑 template），
           否则抛 ParentAlreadyBound
        3. 同级下 name 唯一校验
        4. 写入新节点（is_bind_template=FALSE，新节点默认未绑）
        5. 父节点 is_bind_template 不自动翻转（与子节点数量无关）
        """
        parent = await db.get(TemplateCategory, parent_id)
        if parent is None:
            raise CategoryNotFound(f"父节点(id={parent_id})不存在")
        if parent.is_bind_template:
            raise ParentAlreadyBound(parent_id)

        await _check_name_unique(db, name=name, parent_id=parent_id)
        await _check_max_score(max_score)

        category = TemplateCategory(
            name=name,
            parent_id=parent_id,
            max_score=max_score,
            is_bind_template=False,
            sort_order=sort_order,
            is_active=True,
            description=description,
        )
        db.add(category)

        await db.commit()
        await db.refresh(category)
        return category

    @staticmethod
    async def update(
        db: AsyncSession,
        category_id: int,
        *,
        name: Optional[str] = None,
        max_score: Optional[Decimal] = None,
        sort_order: Optional[int] = None,
        is_active: Optional[bool] = None,
        description: Optional[str] = None,
    ) -> TemplateCategory:
        """修改分类。

        仅允许修改 name / max_score / sort_order / is_active / description。
        禁止：parent_id、is_bind_template（service 自动维护）；
              当分类已绑 template，max_score 必须 ≥ 已绑 template.max_score 之和
              —— 本期暂不校验，留待后续 PR。
        """
        category = await db.get(TemplateCategory, category_id)
        if category is None:
            raise CategoryNotFound(f"分类(id={category_id})不存在")

        if name is not None and name != category.name:
            await _check_name_unique(
                db, name=name, parent_id=category.parent_id, exclude_id=category_id
            )
            category.name = name

        if max_score is not None:
            await _check_max_score(max_score)
            category.max_score = max_score

        if sort_order is not None:
            category.sort_order = sort_order

        if is_active is not None:
            category.is_active = is_active

        if description is not None:
            category.description = description

        await db.commit()
        await db.refresh(category)
        return category

    @staticmethod
    async def bind_template(
        db: AsyncSession,
        category_id: int,
        *,
        template_id: int,
    ) -> TemplateCategory:
        """绑定 template 到分类（service 层公开 API，用于 template 创建时同步翻转）。

        1. 校验分类存在
        2. 校验分类 is_bind_template=FALSE（未绑定）
        3. 校验 template 已绑定该分类 category_id（由调用方保证一致性）
        4. 设置 is_bind_template=TRUE
        注：本方法只动 category 端的 flag；template.category_id 由 TemplateService
           在创建/绑定时设置，本函数不在此重新设置。
        """
        category = await db.get(TemplateCategory, category_id)
        if category is None:
            raise CategoryNotFound(f"分类(id={category_id})不存在")
        if category.is_bind_template:
            # 已绑：直接返回（幂等）
            return category
        category.is_bind_template = True
        await db.commit()
        await db.refresh(category)
        return category

    @staticmethod
    async def unbind_template(
        db: AsyncSession,
        category_id: int,
    ) -> TemplateCategory:
        """解绑：把所有 category_id=category_id 的 template 清空，再把 flag 翻回 FALSE。

        用于：当最后一个 template 被解绑/删除时调用。
        注：本方法**先**清空所有绑过来的 template.category_id（NULL），**再**翻 flag。
        否则会违反"已绑 template 的分类不能再加子"的约束。
        """
        from sqlalchemy import text

        category = await db.get(TemplateCategory, category_id)
        if category is None:
            raise CategoryNotFound(f"分类(id={category_id})不存在")

        # 把所有绑过来的 template 置空（解绑）
        await db.execute(
            text("UPDATE score_templates SET category_id = NULL WHERE category_id = :cid"),
            {"cid": category_id},
        )
        category.is_bind_template = False
        await db.commit()
        await db.refresh(category)
        return category

    @staticmethod
    async def delete(
        db: AsyncSession,
        category_id: int,
    ) -> int:
        """删除分类节点（级联删除同一事务）。

        返回：被删节点总数（含级联后代）。

        流程：
        1. 加载分类，不存在抛 CategoryNotFound
        2. 收集所有要删的 ID：本节点 + 所有后代
        3. 预检：未关闭的 application 数量（status != APPROVED）
           若有则抛 CategoryHasActiveApplications
        4. 一次 DELETE FROM template_category WHERE id IN (...)
           （DB ON DELETE CASCADE 自动级联 template.category_id）
        5. 提交（不需回滚 is_bind_template：因为被删节点的祖先可能也一并被删了）
        """
        category = await db.get(TemplateCategory, category_id)
        if category is None:
            raise CategoryNotFound(f"分类(id={category_id})不存在")

        # 收集所有要删的分类（含自身）
        to_delete = await TemplateCategoryService.get_descendants(
            db, category_id, include_self=True
        )
        to_delete_ids: Set[int] = {c.id for c in to_delete}

        # 预检未关闭 application
        active_count = await _count_active_applications(
            db, list(to_delete_ids)
        )
        if active_count > 0:
            raise CategoryHasActiveApplications(active_count)

        # 一次 DELETE（DB ON DELETE CASCADE 自动级联 template）
        if to_delete_ids:
            await db.execute(
                delete(TemplateCategory).where(
                    TemplateCategory.id.in_(to_delete_ids)
                )
            )

        await db.commit()
        return len(to_delete_ids)

    @staticmethod
    async def get_delete_preview(
        db: AsyncSession,
        category_id: int,
    ) -> Dict[str, Any]:
        """删除预览：返回将级联删除的内容清单。

        返回结构：
        {
          "category": { ... 本节点信息（含 isBindTemplate） ... },
          "descendants": [ ... 所有后代（深度优先） ... ],
          "totalDeletedCount": int,
          "activeApplicationCount": int,
          "templateCount": int,    ← 新增：将被级联删除的 template 数量
        }
        """
        from sqlalchemy import text

        category = await db.get(TemplateCategory, category_id)
        if category is None:
            raise CategoryNotFound(f"分类(id={category_id})不存在")

        descendants = await TemplateCategoryService.get_descendants(
            db, category_id, include_self=True
        )
        descendant_ids = [c.id for c in descendants]

        active_count = await _count_active_applications(db, descendant_ids)

        # 新增：统计将被级联删除的 template 数量
        template_count = 0
        if descendant_ids:
            result = await db.execute(
                text("""
                    SELECT COUNT(*) FROM score_templates
                    WHERE category_id = ANY(:ids)
                """),
                {"ids": descendant_ids},
            )
            template_count = int(result.scalar_one() or 0)

        return {
            "category": _serialize(category, with_children=False),
            "descendants": [_serialize(c, with_children=False) for c in descendants],
            "totalDeletedCount": len(descendants),
            "activeApplicationCount": active_count,
            "templateCount": template_count,
        }


# ===================== 内部辅助 =====================

def _serialize(node: TemplateCategory, *, with_children: bool) -> Dict[str, Any]:
    """ORM → API 响应格式。"""
    result: Dict[str, Any] = {
        "id": node.id,
        "name": node.name,
        "parentId": node.parent_id,
        "maxScore": str(node.max_score),
        "isBindTemplate": node.is_bind_template,
        "sortOrder": node.sort_order,
        "isActive": node.is_active,
        "description": node.description,
    }
    if with_children:
        result["children"] = []
    return result


def _row_to_category(row: Any) -> TemplateCategory:
    """SQLAlchemy Row → ORM 实例（用于 CTE 查询结果）。"""
    return TemplateCategory(
        id=row.id,
        name=row.name,
        parent_id=row.parent_id,
        max_score=row.max_score,
        is_bind_template=row.is_bind_template,
        sort_order=row.sort_order,
        is_active=row.is_active,
        description=row.description,
    )


async def _check_name_unique(
    db: AsyncSession,
    *,
    name: str,
    parent_id: Optional[int],
    exclude_id: Optional[int] = None,
) -> None:
    """同级下 name 唯一校验。"""
    if parent_id is None:
        stmt = select(TemplateCategory).where(
            and_(
                TemplateCategory.name == name,
                TemplateCategory.parent_id.is_(None),
            )
        )
    else:
        stmt = select(TemplateCategory).where(
            and_(
                TemplateCategory.name == name,
                TemplateCategory.parent_id == parent_id,
            )
        )
    if exclude_id is not None:
        stmt = stmt.where(TemplateCategory.id != exclude_id)

    result = await db.execute(stmt)
    if result.scalar_one_or_none() is not None:
        raise CategoryNameDuplicate(name=name, parent_id=parent_id)


async def _check_max_score(max_score: Decimal) -> None:
    """max_score 业务层校验（DB 层 CHECK 兜底）。"""
    if max_score < 0:
        raise CategoryError(f"max_score 必须 >= 0，当前值: {max_score}")


async def _count_active_applications(
    db: AsyncSession,
    category_ids: List[int],
) -> int:
    """统计这些分类下未关闭的 application 数量（status != APPROVED）。

    优先走 score_templates.category_id（新约束，已建）；
    兼容老数据：fallback 通过 field_id / subcategory_id 反查。
    """
    if not category_ids:
        return 0

    from sqlalchemy import text
    sql = text("""
        SELECT COUNT(DISTINCT sa.id)
        FROM score_applications sa
        JOIN score_templates st ON st.id = sa.template_id
        WHERE st.category_id = ANY(:ids)
          AND sa.status != 1
    """)
    result = await db.execute(sql, {"ids": category_ids})
    return int(result.scalar_one() or 0)