"""Attribute 数据访问层（v4 设计）

职责：只做"读 / 写 ORM"，**没有业务规则**；service 校验 type / group_name / value 等。
"""
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import select, delete, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.template import Attribute


class AttributeRepository:
    """attribute 表的数据访问层。"""

    # ---------- 读 ----------

    @staticmethod
    async def list_paged(
        db: AsyncSession,
        *,
        is_active: Optional[bool] = None,
        attr_type: Optional[str] = None,
        group_code: Optional[str] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> List[Attribute]:
        """分页列表。"""
        stmt = select(Attribute).order_by(
            Attribute.group_code.asc(),
            Attribute.sort_order.asc(),
            Attribute.id.asc(),
        )
        if is_active is not None:
            stmt = stmt.where(Attribute.is_active == is_active)
        if attr_type is not None:
            stmt = stmt.where(Attribute.type == attr_type)
        if group_code is not None:
            stmt = stmt.where(Attribute.group_code == group_code)
        stmt = stmt.offset(offset).limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def count(
        db: AsyncSession,
        *,
        is_active: Optional[bool] = None,
        attr_type: Optional[str] = None,
        group_code: Optional[str] = None,
    ) -> int:
        stmt = select(func.count(Attribute.id))
        if is_active is not None:
            stmt = stmt.where(Attribute.is_active == is_active)
        if attr_type is not None:
            stmt = stmt.where(Attribute.type == attr_type)
        if group_code is not None:
            stmt = stmt.where(Attribute.group_code == group_code)
        result = await db.execute(stmt)
        return int(result.scalar_one() or 0)

    @staticmethod
    async def get_by_id(db: AsyncSession, attribute_id: int) -> Optional[Attribute]:
        return await db.get(Attribute, attribute_id)

    @staticmethod
    async def get_by_group_code(
        db: AsyncSession,
        group_code: str,
    ) -> Optional[Attribute]:
        """按 group_code 取首个 attribute（用于 service 推断同组 group_name）。"""
        stmt = (
            select(Attribute)
            .where(Attribute.group_code == group_code)
            .order_by(Attribute.id.asc())
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_by_rule_id(
        db: AsyncSession,
        rule_id: int,
    ) -> List[Attribute]:
        """通过 rule_attribute 关联表查询 rule 已绑的 attribute。"""
        from src.models.template import RuleAttribute

        stmt = (
            select(Attribute)
            .join(RuleAttribute, RuleAttribute.attribute_id == Attribute.id)
            .where(RuleAttribute.rule_id == rule_id)
            .where(Attribute.is_active == True)
            .order_by(Attribute.sort_order.asc(), Attribute.id.asc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    # ---------- 写 ----------

    @staticmethod
    async def insert(db: AsyncSession, attribute: Attribute) -> Attribute:
        db.add(attribute)
        await db.flush()
        return attribute

    @staticmethod
    async def apply_update_fields(
        attr: Attribute,
        *,
        name: Optional[str] = None,
        group_code: Optional[str] = None,
        group_name: Optional[str] = None,
        type: Optional[str] = None,
        value: Optional[str] = None,
        input_min: Optional[Decimal] = None,
        input_max: Optional[Decimal] = None,
        sort_order: Optional[int] = None,
        description: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> bool:
        """就地修改 ORM 字段（无 commit）。

        注：input_min / input_max 不接受 None（无法区分"未传"和"显式 None"）。
        如需清空区间，请走专用 service.clear_input_range 方法（v4 第一版暂不实现）。
        """
        modified = False
        if name is not None:
            attr.name = name
            modified = True
        if group_code is not None:
            attr.group_code = group_code
            modified = True
        if group_name is not None:
            attr.group_name = group_name
            modified = True
        if type is not None:
            attr.type = type
            modified = True
        if value is not None:
            attr.value = value
            modified = True
        if input_min is not None:
            attr.input_min = input_min
            modified = True
        if input_max is not None:
            attr.input_max = input_max
            modified = True
        if sort_order is not None:
            attr.sort_order = sort_order
            modified = True
        if description is not None:
            attr.description = description
            modified = True
        if is_active is not None:
            attr.is_active = is_active
            modified = True
        return modified

    @staticmethod
    async def delete(db: AsyncSession, attribute_id: int) -> int:
        """删除 attribute（FK CASCADE 自动清理 rule_attribute 行）。"""
        stmt = delete(Attribute).where(Attribute.id == attribute_id)
        result = await db.execute(stmt)
        return int(result.rowcount or 0)

    # ---------- 事务辅助 ----------

    @staticmethod
    async def commit(db: AsyncSession) -> None:
        await db.commit()

    @staticmethod
    async def refresh(db: AsyncSession, obj) -> None:
        await db.refresh(obj)


__all__ = ["AttributeRepository"]