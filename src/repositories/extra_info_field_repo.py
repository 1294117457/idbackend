"""ExtraInfoField 数据访问层

职责范围：
- 只做"读 / 写 ORM"，没有业务规则
- 所有 SQLAlchemy 调用集中在此
- 不抛业务异常：由 service 决定翻译为哪种业务异常
"""
from typing import List, Optional

from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.extra_info_field import ExtraInfoField


class ExtraInfoFieldRepository:
    """extra_info_field 表的数据访问层。"""

    # ---------- 读 ----------

    @staticmethod
    async def list_all(
        db: AsyncSession,
        *,
        include_inactive: bool = False,
    ) -> List[ExtraInfoField]:
        """返回所有字段，按 sort_order ASC, id ASC 排序。"""
        stmt = (
            select(ExtraInfoField)
            .order_by(ExtraInfoField.sort_order.asc(), ExtraInfoField.id.asc())
        )
        if not include_inactive:
            stmt = stmt.where(ExtraInfoField.is_active == True)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        field_id: int,
    ) -> Optional[ExtraInfoField]:
        """按主键查；不存在返回 None。"""
        return await db.get(ExtraInfoField, field_id)

    @staticmethod
    async def count(
        db: AsyncSession,
        *,
        include_inactive: bool = False,
    ) -> int:
        """满足 is_active 条件的总数。"""
        stmt = select(func.count(ExtraInfoField.id))
        if not include_inactive:
            stmt = stmt.where(ExtraInfoField.is_active == True)
        result = await db.execute(stmt)
        return int(result.scalar_one() or 0)

    # ---------- 写 ----------

    @staticmethod
    async def insert(
        db: AsyncSession,
        *,
        name: str,
        type: str,
        options: Optional[List[str]] = None,
        sort_order: int = 0,
        description: Optional[str] = None,
    ) -> ExtraInfoField:
        """插入新字段。"""
        field = ExtraInfoField(
            name=name,
            type=type,
            options=options or [],
            sort_order=sort_order,
            is_active=True,
            description=description,
        )
        db.add(field)
        await db.flush()
        return field

    @staticmethod
    async def apply_update_fields(
        field: ExtraInfoField,
        *,
        name: Optional[str] = None,
        type: Optional[str] = None,
        options: Optional[List[str]] = None,
        sort_order: Optional[int] = None,
        is_active: Optional[bool] = None,
        description: Optional[str] = None,
    ) -> bool:
        """就地修改 ORM 字段（不 commit，事务由 caller 负责）。

        返回 True 表示至少修改了一个字段。
        """
        modified = False
        if name is not None:
            field.name = name
            modified = True
        if type is not None:
            field.type = type
            modified = True
        if options is not None:
            field.options = options
            modified = True
        if sort_order is not None:
            field.sort_order = sort_order
            modified = True
        if is_active is not None:
            field.is_active = is_active
            modified = True
        if description is not None:
            field.description = description
            modified = True
        return modified

    @staticmethod
    async def delete_by_id(db: AsyncSession, field_id: int) -> bool:
        """按 id 删除，返回是否删到行。"""
        stmt = delete(ExtraInfoField).where(ExtraInfoField.id == field_id)
        result = await db.execute(stmt)
        return (result.rowcount or 0) > 0

    @staticmethod
    async def commit(db: AsyncSession) -> None:
        await db.commit()

    @staticmethod
    async def refresh(db: AsyncSession, obj: ExtraInfoField) -> None:
        await db.refresh(obj)


__all__ = ["ExtraInfoFieldRepository"]
