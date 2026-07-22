"""Embedding 数据访问层

职责：
- 只做"读 / 写 ORM"，**没有业务规则**
- 所有 SQLAlchemy 调用集中在此
"""
from typing import List, Optional, Tuple

from sqlalchemy import select, delete, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.embedding import Embedding


class EmbeddingRepository:
    """embeddings 表的数据访问层。"""

    # ---------- 读 ----------

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        embedding_id: int,
    ) -> Optional[Embedding]:
        """按主键查。"""
        return await db.get(Embedding, embedding_id)

    @staticmethod
    async def list_by_category(
        db: AsyncSession,
        category: str,
        *,
        limit: int = 1000,
    ) -> List[Embedding]:
        """按 category 查询。"""
        stmt = (
            select(Embedding)
            .where(Embedding.category == category)
            .order_by(Embedding.id.asc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_by_ref_id(
        db: AsyncSession,
        category: str,
        ref_id: int,
    ) -> Optional[Embedding]:
        """按 category + ref_id 查（唯一）。"""
        stmt = select(Embedding).where(
            and_(
                Embedding.category == category,
                Embedding.ref_id == ref_id,
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def count_by_category(
        db: AsyncSession,
        category: str,
    ) -> int:
        """统计某 category 下的数量。"""
        stmt = select(func.count(Embedding.id)).where(
            Embedding.category == category
        )
        result = await db.execute(stmt)
        return int(result.scalar_one() or 0)

    @staticmethod
    async def count_all(db: AsyncSession) -> int:
        """统计总数。"""
        stmt = select(func.count(Embedding.id))
        result = await db.execute(stmt)
        return int(result.scalar_one() or 0)

    @staticmethod
    async def paginate(
        db: AsyncSession,
        *,
        category: Optional[str] = None,
        keyword: Optional[str] = None,
        page_num: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[Embedding], int]:
        """分页查询。

        Returns:
            (items, total) - 数据列表和总数
        """
        conds = []
        if category:
            conds.append(Embedding.category == category)
        if keyword:
            keyword_pattern = f"%{keyword}%"
            conds.append(
                or_(
                    Embedding.title.ilike(keyword_pattern),
                    Embedding.content.ilike(keyword_pattern),
                )
            )

        # 查询总数
        count_stmt = select(func.count(Embedding.id))
        if conds:
            count_stmt = count_stmt.where(and_(*conds))
        count_result = await db.execute(count_stmt)
        total = int(count_result.scalar_one() or 0)

        # 查询分页数据
        offset = (page_num - 1) * page_size
        stmt = (
            select(Embedding)
            .order_by(Embedding.id.desc())
            .offset(offset)
            .limit(page_size)
        )
        if conds:
            stmt = stmt.where(and_(*conds))
        result = await db.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    @staticmethod
    async def get_category_stats(db: AsyncSession) -> dict:
        """获取各分类的统计信息。"""
        stmt = (
            select(Embedding.category, func.count(Embedding.id))
            .group_by(Embedding.category)
        )
        result = await db.execute(stmt)
        return {row[0]: row[1] for row in result.all()}

    # ---------- 写 ----------

    @staticmethod
    async def insert(db: AsyncSession, embedding: Embedding) -> Embedding:
        """插入新 embedding。"""
        db.add(embedding)
        await db.flush()
        return embedding

    @staticmethod
    async def update(db: AsyncSession, embedding: Embedding) -> Embedding:
        """更新 embedding。"""
        await db.flush()
        return embedding

    @staticmethod
    async def upsert(
        db: AsyncSession,
        *,
        title: Optional[str],
        content: str,
        category: str,
        ref_id: Optional[int],
        embedding_vector: list[float],
    ) -> Embedding:
        """upsert：按 category + ref_id 存在则更新，不存在则插入。

        用于模板更新时同步更新向量。
        """
        if ref_id is not None:
            existing = await EmbeddingRepository.get_by_ref_id(
                db, category, ref_id
            )
            if existing is not None:
                existing.title = title
                existing.content = content
                existing.embedding = embedding_vector
                await db.flush()
                return existing

        new_embedding = Embedding(
            title=title,
            content=content,
            category=category,
            ref_id=ref_id,
            embedding=embedding_vector,
        )
        db.add(new_embedding)
        await db.flush()
        return new_embedding

    @staticmethod
    async def delete_by_ids(
        db: AsyncSession,
        ids: List[int],
    ) -> int:
        """按主键列表批量删除。"""
        if not ids:
            return 0
        stmt = delete(Embedding).where(Embedding.id.in_(ids))
        result = await db.execute(stmt)
        return int(result.rowcount or 0)

    @staticmethod
    async def delete_by_ref_id(
        db: AsyncSession,
        category: str,
        ref_id: int,
    ) -> int:
        """按 category + ref_id 删除。"""
        stmt = delete(Embedding).where(
            and_(
                Embedding.category == category,
                Embedding.ref_id == ref_id,
            )
        )
        result = await db.execute(stmt)
        return int(result.rowcount or 0)

    @staticmethod
    async def delete_by_id(
        db: AsyncSession,
        embedding_id: int,
    ) -> int:
        """按主键删除。"""
        stmt = delete(Embedding).where(Embedding.id == embedding_id)
        result = await db.execute(stmt)
        return int(result.rowcount or 0)

    # ---------- 事务辅助 ----------

    @staticmethod
    async def commit(db: AsyncSession) -> None:
        await db.commit()

    @staticmethod
    async def refresh(db: AsyncSession, obj: Embedding) -> None:
        await db.refresh(obj)


__all__ = ["EmbeddingRepository"]
