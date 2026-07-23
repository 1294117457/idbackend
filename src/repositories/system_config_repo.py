"""SystemConfig 数据访问层

职责：
- 只做"读 / 写 ORM"，没有业务规则
- 所有 SQLAlchemy 调用集中在此
- 不抛业务异常，not-found / dup-key 返回 None / bool
"""

from typing import List, Optional

from sqlalchemy import select, update, delete, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.system_config import SystemConfig


class SystemConfigRepository:
    """system_config 表的数据访问层"""

    # ---------- 读 ----------

    @staticmethod
    async def get_by_key(db: AsyncSession, config_key: str) -> Optional[SystemConfig]:
        """按 config_key 查单条"""
        return await db.get(SystemConfig, config_key)

    @staticmethod
    async def list_by_category(db: AsyncSession, category: str) -> List[SystemConfig]:
        """按分类查询所有配置"""
        stmt = select(SystemConfig).where(SystemConfig.category == category).order_by(SystemConfig.config_key)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def list_all(db: AsyncSession) -> List[SystemConfig]:
        """查询所有配置"""
        stmt = select(SystemConfig).order_by(SystemConfig.category, SystemConfig.config_key)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def list_keys(db: AsyncSession, config_keys: List[str]) -> List[SystemConfig]:
        """按 key 列表批量查询"""
        if not config_keys:
            return []
        stmt = select(SystemConfig).where(SystemConfig.config_key.in_(config_keys))
        result = await db.execute(stmt)
        return list(result.scalars().all())

    # ---------- 写 ----------

    @staticmethod
    async def upsert(
        db: AsyncSession,
        config_key: str,
        config_value: str,
        *,
        description: Optional[str] = None,
        category: str = "OTHER",
        value_type: str = "string",
        is_sensitive: bool = False,
    ) -> SystemConfig:
        """UPSERT 配置（不存在则插入，存在则更新）"""
        stmt = pg_insert(SystemConfig).values(
            config_key=config_key,
            config_value=config_value,
            description=description,
            category=category,
            value_type=value_type,
            is_sensitive=is_sensitive,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["config_key"],
            set_={
                "config_value": stmt.excluded.config_value,
                "description": stmt.excluded.description,
                "category": stmt.excluded.category,
                "value_type": stmt.excluded.value_type,
                "is_sensitive": stmt.excluded.is_sensitive,
            },
        )
        await db.execute(stmt)
        await db.commit()
        return await SystemConfigRepository.get_by_key(db, config_key)

    @staticmethod
    async def delete(db: AsyncSession, config_key: str) -> bool:
        """删除指定配置"""
        stmt = delete(SystemConfig).where(SystemConfig.config_key == config_key)
        result = await db.execute(stmt)
        await db.commit()
        return result.rowcount > 0

    @staticmethod
    async def batch_delete(db: AsyncSession, config_keys: List[str]) -> int:
        """批量删除"""
        if not config_keys:
            return 0
        stmt = delete(SystemConfig).where(SystemConfig.config_key.in_(config_keys))
        result = await db.execute(stmt)
        await db.commit()
        return result.rowcount
