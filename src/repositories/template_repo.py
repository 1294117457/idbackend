"""Template 数据访问层（v4 设计）

职责：
- 只做"读 / 写 ORM"，**没有业务规则**
- 所有 SQLAlchemy 调用集中在此；service 通过它返回 ORM/list/dict
- 不抛业务异常：not-found / dup-name 一律返回 None / bool，由 service 翻译

约定：
- 静态方法风格（对齐 TemplateCategoryRepository / FileService）
- selectinload 一次 JOIN 完整规则树（template → rules → attributes），避免 N+1
"""
from decimal import Decimal
from typing import List, Optional, Iterable

from sqlalchemy import select, update, delete, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.template import Template, Rule, Attribute, TemplateRule, RuleAttribute


class TemplateRepository:
    """template 表的数据访问层。"""

    # ---------- 读 ----------

    @staticmethod
    async def list_paged(
        db: AsyncSession,
        *,
        category_id: Optional[int] = None,
        is_active: Optional[bool] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> List[Template]:
        """分页列表（带过滤）。"""
        stmt = select(Template).order_by(
            Template.sort_order.asc(),
            Template.id.asc(),
        )
        if category_id is not None:
            stmt = stmt.where(Template.category_id == category_id)
        if is_active is not None:
            stmt = stmt.where(Template.is_active == is_active)
        stmt = stmt.offset(offset).limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def count(
        db: AsyncSession,
        *,
        category_id: Optional[int] = None,
        is_active: Optional[bool] = None,
    ) -> int:
        """统计数量。"""
        stmt = select(func.count(Template.id))
        if category_id is not None:
            stmt = stmt.where(Template.category_id == category_id)
        if is_active is not None:
            stmt = stmt.where(Template.is_active == is_active)
        result = await db.execute(stmt)
        return int(result.scalar_one() or 0)

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        template_id: int,
    ) -> Optional[Template]:
        """按主键查。"""
        return await db.get(Template, template_id)

    @staticmethod
    async def get_with_rules(
        db: AsyncSession,
        template_id: int,
    ) -> Optional[Template]:
        """加载模板 + 完整规则树（template → rules → attributes），3 条 SQL。

        性能优化：避免前端按 rule / attribute 多次请求产生的 N+1。
        """
        stmt = (
            select(Template)
            .where(Template.id == template_id)
            .options(
                selectinload(Template.rules).selectinload(Rule.attributes),
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_by_category(
        db: AsyncSession,
        category_id: int,
        *,
        is_active: bool = True,
    ) -> List[Template]:
        """按分类 ID 列出模板（学生端选 template 用）。"""
        stmt = (
            select(Template)
            .where(Template.category_id == category_id)
            .order_by(Template.sort_order.asc(), Template.id.asc())
        )
        if is_active:
            stmt = stmt.where(Template.is_active == True)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_rule_types(
        db: AsyncSession,
        template_id: int,
    ) -> List[str]:
        """获取 template 已绑 rule 的 type 集合（用于 is_mixed_type 计算）。

        实现：先取 template_rule 行 → join rule 表的 type 列 → distinct。
        比拉全 rule 对象更轻量。
        """
        stmt = (
            select(func.distinct(Rule.type))
            .select_from(TemplateRule)
            .join(Rule, Rule.id == TemplateRule.rule_id)
            .where(TemplateRule.template_id == template_id)
            .where(Rule.is_active == True)
        )
        result = await db.execute(stmt)
        return [row[0] for row in result.all()]

    @staticmethod
    async def count_active_applications(
        db: AsyncSession,
        template_ids: Iterable[int],
    ) -> int:
        """统计这些 template 下未关闭的 application 数量（status != 'PASSED'）。

        与 TemplateCategoryRepository.count_active_applications 区分：
        - CategoryService 关心 category 下 application 数；
        - TemplateService 关心 template 下 application 数。
        """
        from src.models.application import Application

        ids = list(template_ids)
        if not ids:
            return 0

        stmt = (
            select(func.count(func.distinct(Application.id)))
            .where(Application.template_id.in_(ids))
            .where(Application.status != "PASSED")
        )
        result = await db.execute(stmt)
        return int(result.scalar_one() or 0)

    # ---------- 写 ----------

    @staticmethod
    async def insert(db: AsyncSession, template: Template) -> Template:
        """插入新 template。"""
        db.add(template)
        await db.flush()
        return template

    @staticmethod
    async def apply_update_fields(
        template: Template,
        *,
        name: Optional[str] = None,
        max_score: Optional[Decimal] = None,
        review_count: Optional[int] = None,
        sort_order: Optional[int] = None,
        description: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> bool:
        """就地修改 ORM 字段（无 commit）。"""
        modified = False
        if name is not None:
            template.name = name
            modified = True
        if max_score is not None:
            template.max_score = max_score
            modified = True
        if review_count is not None:
            template.review_count = review_count
            modified = True
        if sort_order is not None:
            template.sort_order = sort_order
            modified = True
        if description is not None:
            template.description = description
            modified = True
        if is_active is not None:
            template.is_active = is_active
            modified = True
        return modified

    @staticmethod
    async def bind_rule(
        db: AsyncSession,
        template_id: int,
        rule_id: int,
    ) -> Optional[TemplateRule]:
        """绑定 rule 到 template（幂等：不抛重复键异常）。"""
        existing = await db.execute(
            select(TemplateRule).where(
                and_(
                    TemplateRule.template_id == template_id,
                    TemplateRule.rule_id == rule_id,
                )
            )
        )
        if existing.scalar_one_or_none() is not None:
            return None  # 已存在，幂等返回

        link = TemplateRule(template_id=template_id, rule_id=rule_id)
        db.add(link)
        await db.flush()
        return link

    @staticmethod
    async def unbind_rule(
        db: AsyncSession,
        template_id: int,
        rule_id: int,
    ) -> int:
        """解绑 rule（返回受影响行数）。"""
        stmt = delete(TemplateRule).where(
            and_(
                TemplateRule.template_id == template_id,
                TemplateRule.rule_id == rule_id,
            )
        )
        result = await db.execute(stmt)
        return int(result.rowcount or 0)

    @staticmethod
    async def get_bound_rule_ids(
        db: AsyncSession,
        template_id: int,
    ) -> List[int]:
        """返回 template 已绑的 rule_id 列表（按 rule.sort_order 排序）。"""
        stmt = (
            select(Rule.id)
            .select_from(TemplateRule)
            .join(Rule, Rule.id == TemplateRule.rule_id)
            .where(TemplateRule.template_id == template_id)
            .where(Rule.is_active == True)
            .order_by(Rule.sort_order.asc(), Rule.id.asc())
        )
        result = await db.execute(stmt)
        return [row[0] for row in result.all()]

    @staticmethod
    async def delete(db: AsyncSession, template_id: int) -> int:
        """删除 template（FK CASCADE 自动清理 template_rule 行）。"""
        stmt = delete(Template).where(Template.id == template_id)
        result = await db.execute(stmt)
        return int(result.rowcount or 0)

    # ---------- 事务辅助 ----------

    @staticmethod
    async def commit(db: AsyncSession) -> None:
        await db.commit()

    @staticmethod
    async def refresh(db: AsyncSession, obj) -> None:
        await db.refresh(obj)


__all__ = ["TemplateRepository"]