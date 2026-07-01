"""需求模板和申请服务"""
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
import json

from src.models import DemandTemplate


class DemandTemplateService:
    """需求模板服务"""

    @staticmethod
    async def get_active(db: AsyncSession) -> List[DemandTemplate]:
        """获取启用的模板"""
        result = await db.execute(
            select(DemandTemplate)
            .where(DemandTemplate.is_active == True)
            .order_by(DemandTemplate.sort_order)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_all(db: AsyncSession) -> List[DemandTemplate]:
        """获取所有模板"""
        result = await db.execute(
            select(DemandTemplate).order_by(DemandTemplate.sort_order)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_id(db: AsyncSession, template_id: int) -> Optional[DemandTemplate]:
        """根据ID获取模板"""
        result = await db.execute(
            select(DemandTemplate).where(DemandTemplate.id == template_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create(
        db: AsyncSession,
        template_name: str,
        conditions: Optional[List[str]] = None,
        description: Optional[str] = None,
        created_by: str = "system",
        sort_order: int = 0,
    ) -> DemandTemplate:
        """创建需求模板"""
        template = DemandTemplate(
            template_name=template_name,
            conditions=conditions or [],
            description=description,
            created_by=created_by,
            sort_order=sort_order,
            is_active=True,
        )
        db.add(template)
        await db.commit()
        await db.refresh(template)
        return template

    @staticmethod
    async def update(
        db: AsyncSession,
        template_id: int,
        **kwargs,
    ) -> Optional[DemandTemplate]:
        """更新需求模板"""
        template = await DemandTemplateService.get_by_id(db, template_id)
        if not template:
            return None

        for key, value in kwargs.items():
            if hasattr(template, key) and value is not None:
                setattr(template, key, value)

        await db.commit()
        await db.refresh(template)
        return template

    @staticmethod
    async def delete(db: AsyncSession, template_id: int) -> bool:
        """删除需求模板"""
        template = await DemandTemplateService.get_by_id(db, template_id)
        if not template:
            return False

        await db.delete(template)
        await db.commit()
        return True
