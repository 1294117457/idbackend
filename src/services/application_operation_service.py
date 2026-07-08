"""申请操作审计服务（v4.3）

只读接口（v4.3 不在本 service 写 operation——写在 application_service 内）。
operation.status 直接存储操作后的 application 状态。
"""
from __future__ import annotations

from typing import List

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import ApplicationOperation, ApplicationStatus


class ApplicationOperationService:
    """申请操作审计服务"""

    @staticmethod
    async def list_by_application(
        db: AsyncSession,
        application_id: int,
    ) -> List[ApplicationOperation]:
        """返回 application 全部操作历史，按 created_at ASC"""
        result = await db.execute(
            select(ApplicationOperation)
            .where(ApplicationOperation.application_id == application_id)
            .order_by(ApplicationOperation.created_at.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_votes(
        db: AsyncSession,
        application_id: int,
    ) -> List[ApplicationOperation]:
        """仅返回 status IN ('PASSED','REJECTED') 的投票记录"""
        result = await db.execute(
            select(ApplicationOperation)
            .where(
                and_(
                    ApplicationOperation.application_id == application_id,
                    ApplicationOperation.status.in_([
                        ApplicationStatus.PASSED.value,
                        ApplicationStatus.REJECTED.value,
                    ]),
                )
            )
            .order_by(ApplicationOperation.created_at.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def has_voted(
        db: AsyncSession,
        application_id: int,
        operator_id: int,
    ) -> bool:
        """判断 (application_id, operator_id) 是否已投过票"""
        result = await db.execute(
            select(func.count())
            .select_from(ApplicationOperation)
            .where(
                and_(
                    ApplicationOperation.application_id == application_id,
                    ApplicationOperation.operator_id == operator_id,
                    ApplicationOperation.status.in_([
                        ApplicationStatus.PASSED.value,
                        ApplicationStatus.REJECTED.value,
                    ]),
                )
            )
        )
        return (result.scalar() or 0) > 0
