"""TemplateCategory 数据访问层

职责范围（与 service 的边界）：
- 只做"读 / 写 ORM"，**没有业务规则**
- 所有 SQLAlchemy 调用集中在此；service 通过它返回 ORM/list/dict
- **不**抛业务异常：not-found / dup-name / bound-state 一律返回 None / bool，
  由 service 决定翻译为哪种业务异常

约定：
- 静态方法风格（对齐 file_service / attribute_service），便于 service 直接调用
- 纯 ORM（无 text(...)、无 CTE），递归 / 路径在 Python 端组装
  说明：分类数 < 数百级别时 Python 端组树完全可以接受；如未来量级爆炸，
  再单独引入 selectinload / 后端 CTE 都不影响 service 调用形态
"""
from decimal import Decimal
from typing import List, Optional, Iterable, Dict

from sqlalchemy import select, update, delete, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.template_category import TemplateCategory


class TemplateCategoryRepository:
    """template_category 表的数据访问层。"""

    # ---------- 读：平铺 / 单条 / 路径 / 后代 ----------

    @staticmethod
    async def list_all(
        db: AsyncSession,
        *,
        include_inactive: bool = False,
        only_bindable: bool = False,
    ) -> List[TemplateCategory]:
        """全表平铺查询。

        - include_inactive=False → 默认过滤 is_active=TRUE
        - only_bindable=True      → 只返回 is_bind_template=FALSE（可供 template 绑定）

        返回列表按 (parent_id nulls first, sort_order, id) 排序，
        方便前端按层级展示，也方便 path / descendants 兜底遍历。
        """
        stmt = select(TemplateCategory).order_by(
            TemplateCategory.parent_id.nulls_first(),
            TemplateCategory.sort_order.asc(),
            TemplateCategory.id.asc(),
        ).where(TemplateCategory.is_deleted == False)
        if not include_inactive:
            stmt = stmt.where(TemplateCategory.is_active == True)
        if only_bindable:
            stmt = stmt.where(TemplateCategory.is_bind_template == False)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def count(
        db: AsyncSession,
        *,
        include_inactive: bool = False,
    ) -> int:
        """满足 is_active 条件（按需）的总数。"""
        stmt = select(func.count(TemplateCategory.id)).where(
            TemplateCategory.is_deleted == False
        )
        if not include_inactive:
            stmt = stmt.where(TemplateCategory.is_active == True)
        result = await db.execute(stmt)
        return int(result.scalar_one() or 0)

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        category_id: int,
    ) -> Optional[TemplateCategory]:
        """按主键查；不存在返回 None（不抛异常，由 service 翻译）。"""
        return await db.get(TemplateCategory, category_id)

    @staticmethod
    async def get_path(
        db: AsyncSession,
        category_id: int,
    ) -> List[TemplateCategory]:
        """返回从根到当前节点的 ORM 路径（含自身）。

        实现：从全表按 parent 链向上爬——N ≤ 数百时 O(N) 内存全查优于递归 CTE。
        """
        nodes = await TemplateCategoryRepository._get_all(db)
        by_id: Dict[int, TemplateCategory] = {n.id: n for n in nodes}
        if category_id not in by_id:
            return []

        chain: List[TemplateCategory] = []
        cur: Optional[TemplateCategory] = by_id.get(category_id)
        while cur is not None:
            chain.append(cur)
            if cur.parent_id is None:
                break
            cur = by_id.get(cur.parent_id)
            if cur is None:
                break
        return list(reversed(chain))

    @staticmethod
    async def get_descendants(
        db: AsyncSession,
        category_id: int,
        *,
        include_self: bool = False,
    ) -> List[TemplateCategory]:
        """返回 category_id 所有后代（深度优先），含自身可选。

        实现：内存 BFS——先取全表建 children_map，再从 start BFS。
        """
        nodes = await TemplateCategoryRepository._get_all(db)
        children_map: Dict[int, List[TemplateCategory]] = {}
        for n in nodes:
            if n.parent_id is not None:
                children_map.setdefault(n.parent_id, []).append(n)

        result: List[TemplateCategory] = []
        visited = set()
        stack = [category_id]
        while stack:
            pid = stack.pop()
            for child in children_map.get(pid, []):
                if child.id in visited:
                    continue
                visited.add(child.id)
                result.append(child)
                stack.append(child.id)

        if include_self:
            start = next((n for n in nodes if n.id == category_id), None)
            if start is not None:
                result.insert(0, start)
        return result

    # ---------- 读：唯一校验 / 计数 ----------

    @staticmethod
    async def find_sibling_by_name(
        db: AsyncSession,
        *,
        name: str,
        parent_id: Optional[int],
        exclude_id: Optional[int] = None,
    ) -> Optional[TemplateCategory]:
        """同级下重名查询；返回首个匹配或 None。

        parent_id 为 None 时取 parent_id IS NULL 的根节点。
        """
        if parent_id is None:
            cond = TemplateCategory.parent_id.is_(None)
        else:
            cond = TemplateCategory.parent_id == parent_id

        stmt = select(TemplateCategory).where(
            and_(
                TemplateCategory.name == name,
                TemplateCategory.is_deleted == False,
                cond,
            )
        )
        if exclude_id is not None:
            stmt = stmt.where(TemplateCategory.id != exclude_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def count_active_applications(
        db: AsyncSession,
        category_ids: Iterable[int],
    ) -> int:
        """统计这些分类下未关闭的 application 数量（status != 'PASSED'）。"""
        from src.models.application import Application
        from src.models.template import Template

        ids = list(category_ids)
        if not ids:
            return 0

        stmt = (
            select(func.count(func.distinct(Application.id)))
            .join(Template, Template.id == Application.template_id)
            .where(Template.category_id.in_(ids))
            .where(Application.status != "PASSED")
        )
        result = await db.execute(stmt)
        return int(result.scalar_one() or 0)

    @staticmethod
    async def count_children(
        db: AsyncSession,
        parent_id: int,
    ) -> int:
        """统计直接子节点数量（利用 parent_id 索引，O(1) 级别）。"""
        stmt = select(func.count(TemplateCategory.id)).where(
            and_(
                TemplateCategory.parent_id == parent_id,
                TemplateCategory.is_deleted == False,
            )
        )
        result = await db.execute(stmt)
        return int(result.scalar_one() or 0)

    @staticmethod
    async def count_templates(
        db: AsyncSession,
        category_ids: Iterable[int],
    ) -> int:
        """统计这些分类下 template 行数（v4：指向新 Template 表）。"""
        from src.models.template import Template

        ids = list(category_ids)
        if not ids:
            return 0

        stmt = (
            select(func.count(Template.id))
            .where(Template.category_id.in_(ids))
        )
        result = await db.execute(stmt)
        return int(result.scalar_one() or 0)

    # ---------- 写 ----------

    @staticmethod
    async def insert(
        db: AsyncSession,
        *,
        name: str,
        parent_id: Optional[int],
        max_score: Decimal,
        description: Optional[str],
        sort_order: int,
    ) -> TemplateCategory:
        """插入新分类（is_bind_template=FALSE 默认）。"""
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
        await db.flush()
        return category

    @staticmethod
    async def apply_update_fields(
        category: TemplateCategory,
        *,
        name: Optional[str] = None,
        max_score: Optional[Decimal] = None,
        sort_order: Optional[int] = None,
        is_active: Optional[bool] = None,
        description: Optional[str] = None,
    ) -> bool:
        """就地修改 ORM 字段（不 commit，事务由 caller 负责）。

        返回 True 表示至少修改了一个字段，False 表示无任何修改（caller 应跳过 commit）。
        """
        modified = False
        if name is not None:
            category.name = name
            modified = True
        if max_score is not None:
            category.max_score = max_score
            modified = True
        if sort_order is not None:
            category.sort_order = sort_order
            modified = True
        if is_active is not None:
            category.is_active = is_active
            modified = True
        if description is not None:
            category.description = description
            modified = True
        return modified

    @staticmethod
    async def set_bind_template(category: TemplateCategory, *, value: bool) -> None:
        """翻转 is_bind_template flag（无 commit，由 caller 管事务）。"""
        category.is_bind_template = value

    @staticmethod
    async def unbind_templates(
        db: AsyncSession,
        category_id: int,
    ) -> int:
        """解除这些 templates.category_id（指向本分类的全部置 NULL）。

        返回受影响行数。
        """
        from src.models.template import Template

        stmt = (
            update(Template)
            .where(Template.category_id == category_id)
            .values(category_id=None)
        )
        result = await db.execute(stmt)
        return int(result.rowcount or 0)

    @staticmethod
    async def soft_delete_many(
        db: AsyncSession,
        category_ids: List[int],
    ) -> int:
        """批量软删除（is_deleted=True）；返回受影响行数。"""
        if not category_ids:
            return 0
        stmt = (
            update(TemplateCategory)
            .where(TemplateCategory.id.in_(category_ids))
            .values(is_deleted=True)
        )
        result = await db.execute(stmt)
        return int(result.rowcount or 0)

    @staticmethod
    async def delete_many(
        db: AsyncSession,
        category_ids: List[int],
    ) -> int:
        """批量物理删除指定 id 的分类；返回受影响行数。"""
        if not category_ids:
            return 0
        stmt = delete(TemplateCategory).where(
            TemplateCategory.id.in_(category_ids)
        )
        result = await db.execute(stmt)
        return int(result.rowcount or 0)




    # ---------- 内部工具 ----------

    @staticmethod
    async def _get_all(db: AsyncSession) -> List[TemplateCategory]:
        """全表查一遍（小幅数据专用）；用于 path / descendants 兜底。"""
        stmt = (
            select(TemplateCategory)
            .where(TemplateCategory.is_deleted == False)
            .order_by(TemplateCategory.id.asc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())


__all__ = ["TemplateCategoryRepository"]


# 兼容别名：旧的"TemplateCategoryRepository"在 service 改造后会改名为该类。
