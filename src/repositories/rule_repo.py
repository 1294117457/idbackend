"""Rule 数据访问层（v4 设计）

职责：只做"读 / 写 ORM"，**没有业务规则**；service 校验 type/score 一致性。
"""
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import select, update, delete, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.template import Rule, Attribute, RuleAttribute


class RuleRepository:
    """rule 表的数据访问层。"""

    # ---------- 读 ----------

    @staticmethod
    async def list_paged(
        db: AsyncSession,
        *,
        is_active: Optional[bool] = None,
        rule_type: Optional[str] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> List[Rule]:
        """分页列表。"""
        stmt = select(Rule).order_by(Rule.sort_order.asc(), Rule.id.asc())
        if is_active is not None:
            stmt = stmt.where(Rule.is_active == is_active)
        if rule_type is not None:
            stmt = stmt.where(Rule.type == rule_type)
        stmt = stmt.offset(offset).limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def count(
        db: AsyncSession,
        *,
        is_active: Optional[bool] = None,
        rule_type: Optional[str] = None,
    ) -> int:
        stmt = select(func.count(Rule.id))
        if is_active is not None:
            stmt = stmt.where(Rule.is_active == is_active)
        if rule_type is not None:
            stmt = stmt.where(Rule.type == rule_type)
        result = await db.execute(stmt)
        return int(result.scalar_one() or 0)

    @staticmethod
    async def get_by_id(db: AsyncSession, rule_id: int) -> Optional[Rule]:
        return await db.get(Rule, rule_id)

    @staticmethod
    async def get_with_attributes(
        db: AsyncSession,
        rule_id: int,
    ) -> Optional[Rule]:
        """加载 rule + 全部 attribute（1 条 SQL）。"""
        stmt = (
            select(Rule)
            .where(Rule.id == rule_id)
            .options(selectinload(Rule.attributes))
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    # ---------- 写 ----------

    @staticmethod
    async def insert(db: AsyncSession, rule: Rule) -> Rule:
        db.add(rule)
        await db.flush()
        return rule

    @staticmethod
    async def apply_update_fields(
        rule: Rule,
        *,
        type: Optional[str] = None,
        score: Optional[Decimal] = None,
        name: Optional[str] = None,
        sort_order: Optional[int] = None,
        description: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> bool:
        """就地修改 ORM 字段（无 commit）。"""
        modified = False
        if type is not None:
            rule.type = type
            modified = True
        if score is not None:
            rule.score = score
            modified = True
        if name is not None:
            rule.name = name
            modified = True
        if sort_order is not None:
            rule.sort_order = sort_order
            modified = True
        if description is not None:
            rule.description = description
            modified = True
        if is_active is not None:
            rule.is_active = is_active
            modified = True
        return modified

    @staticmethod
    async def bind_attribute(
        db: AsyncSession,
        rule_id: int,
        attribute_id: int,
    ) -> Optional[RuleAttribute]:
        """绑定 attribute 到 rule（幂等）。

        返回 None 表示已存在；service 看到 None 时直接跳过，无需额外判断。
        """
        existing = await db.execute(
            select(RuleAttribute).where(
                and_(
                    RuleAttribute.rule_id == rule_id,
                    RuleAttribute.attribute_id == attribute_id,
                )
            )
        )
        if existing.scalar_one_or_none() is not None:
            return None

        link = RuleAttribute(rule_id=rule_id, attribute_id=attribute_id)
        db.add(link)
        await db.flush()
        return link

    @staticmethod
    async def unbind_attribute(
        db: AsyncSession,
        rule_id: int,
        attribute_id: int,
    ) -> int:
        stmt = delete(RuleAttribute).where(
            and_(
                RuleAttribute.rule_id == rule_id,
                RuleAttribute.attribute_id == attribute_id,
            )
        )
        result = await db.execute(stmt)
        return int(result.rowcount or 0)

    @staticmethod
    async def delete(db: AsyncSession, rule_id: int) -> int:
        """删除 rule（FK CASCADE 自动清理 rule_attribute 行）。"""
        stmt = delete(Rule).where(Rule.id == rule_id)
        result = await db.execute(stmt)
        return int(result.rowcount or 0)

    # ---------- v5 复合操作 ----------

    @staticmethod
    async def replace_bound_attributes(
        db: AsyncSession,
        rule_id: int,
        attribute_ids: List[int],
    ) -> None:
        """全量替换 rule 绑定的 attribute（DIFF 语义）

        - 先 DELETE 清空旧绑定
        - 再批量 INSERT 新绑定
        - rule_attribute 表只有 (rule_id, attribute_id)，排序由 attribute.sort_order 决定
        """
        # 清空旧绑定
        await db.execute(
            delete(RuleAttribute).where(RuleAttribute.rule_id == rule_id)
        )
        # 批量插入（去重 + 过滤 None）
        deduped = list({aid for aid in attribute_ids if aid is not None})
        if deduped:
            from sqlalchemy import insert
            await db.execute(
                insert(RuleAttribute),
                [{"rule_id": rule_id, "attribute_id": aid} for aid in deduped],
            )

    @staticmethod
    async def count_bound_templates(
        db: AsyncSession,
        rule_id: int,
    ) -> int:
        """统计该 rule 被多少 template 绑定（用于删除前预检）"""
        from src.models.template import TemplateRule
        result = await db.execute(
            select(func.count(TemplateRule.id))
            .where(TemplateRule.rule_id == rule_id)
        )
        return int(result.scalar_one_or_none() or 0)





__all__ = ["RuleRepository"]