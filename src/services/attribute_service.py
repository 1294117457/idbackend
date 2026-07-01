"""属性服务 - 兼容前端 rule-attribute 接口"""
from sqlalchemy import select, delete, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from typing import Optional, List

from src.models import RuleAttribute, RuleAttributeMapping


class AttributeService:
    """属性管理服务"""

    @staticmethod
    async def get_all_active(db: AsyncSession) -> List[RuleAttribute]:
        """获取所有启用的属性"""
        result = await db.execute(
            select(RuleAttribute)
            .where(RuleAttribute.is_active == True)
            .order_by(RuleAttribute.display_order)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_type(db: AsyncSession, attr_type: str) -> List[RuleAttribute]:
        """根据类型获取属性"""
        result = await db.execute(
            select(RuleAttribute)
            .where(RuleAttribute.attribute_type == attr_type)
            .where(RuleAttribute.is_active == True)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_code(db: AsyncSession, code: str) -> List[RuleAttribute]:
        """根据编码获取属性"""
        result = await db.execute(
            select(RuleAttribute)
            .where(RuleAttribute.attribute_code == code)
            .where(RuleAttribute.is_active == True)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_id(db: AsyncSession, attr_id: int) -> Optional[RuleAttribute]:
        """根据ID获取属性"""
        result = await db.execute(
            select(RuleAttribute).where(RuleAttribute.id == attr_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create(
        db: AsyncSession,
        attribute_code: str,
        attribute_type: str,
        attribute_value: str,
        input_min: Optional[float] = None,
        input_max: Optional[float] = None,
        input_interval: Optional[str] = None,
        display_order: int = 0,
        description: Optional[str] = None,
    ) -> RuleAttribute:
        """创建属性"""
        attr = RuleAttribute(
            attribute_code=attribute_code,
            attribute_type=attribute_type,
            attribute_value=attribute_value,
            input_min=input_min,
            input_max=input_max,
            input_interval=input_interval,
            display_order=display_order,
            description=description,
            is_active=True,
        )
        db.add(attr)
        await db.commit()
        await db.refresh(attr)
        return attr

    @staticmethod
    async def update(
        db: AsyncSession,
        attr_id: int,
        **kwargs,
    ) -> Optional[RuleAttribute]:
        """更新属性"""
        attr = await AttributeService.get_by_id(db, attr_id)
        if not attr:
            return None

        # 唯一键冲突检查 (attribute_code + attribute_value + attribute_type)
        new_value = kwargs.get('attribute_value', attr.attribute_value)
        new_type = kwargs.get('attribute_type', attr.attribute_type)

        existing = await db.execute(
            select(RuleAttribute).where(
                and_(
                    RuleAttribute.attribute_code == attr.attribute_code,
                    RuleAttribute.attribute_value == new_value,
                    RuleAttribute.attribute_type == new_type,
                    RuleAttribute.id != attr_id
                )
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError("该属性值已存在")

        for key, value in kwargs.items():
            if hasattr(attr, key) and value is not None:
                setattr(attr, key, value)

        await db.commit()
        await db.refresh(attr)
        return attr

    @staticmethod
    async def delete(db: AsyncSession, attr_id: int) -> bool:
        """删除属性"""
        # 先删除关联映射
        await db.execute(
            delete(RuleAttributeMapping).where(RuleAttributeMapping.attribute_id == attr_id)
        )
        # 删除属性
        await db.execute(
            delete(RuleAttribute).where(RuleAttribute.id == attr_id)
        )
        await db.commit()
        return True

    @staticmethod
    async def get_attributes_by_rule_id(
        db: AsyncSession,
        rule_id: int,
    ) -> List[RuleAttribute]:
        """获取规则关联的所有属性"""
        result = await db.execute(
            select(RuleAttribute)
            .join(RuleAttributeMapping, RuleAttributeMapping.attribute_id == RuleAttribute.id)
            .where(RuleAttributeMapping.rule_id == rule_id)
            .order_by(RuleAttributeMapping.display_order)
        )
        return list(result.scalars().all())
