"""Embedding 数据访问层

职责：
- 只做"读 / 写 ORM"，**没有业务规则**
- 所有 SQLAlchemy 调用集中在此
"""

from typing import List, Optional, Tuple

from sqlalchemy import select, delete, func, and_, or_
from sqlalchemy.orm import defer
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
    async def list_by_source(
        db: AsyncSession,
        source_id: str,
    ) -> List[Embedding]:
        """按 source_id 查询某来源的所有 chunks。"""
        stmt = (
            select(Embedding)
            .where(Embedding.source_id == source_id)
            .order_by(Embedding.chunk_index.asc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

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
    async def count_by_category(
        db: AsyncSession,
        category: str,
    ) -> int:
        """统计某 category 下的数量。"""
        stmt = select(func.count(Embedding.id)).where(Embedding.category == category)
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
        """分页查询（扁平）。"""
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

        count_stmt = select(func.count(Embedding.id))
        if conds:
            count_stmt = count_stmt.where(and_(*conds))
        count_result = await db.execute(count_stmt)
        total = int(count_result.scalar_one() or 0)

        offset = (page_num - 1) * page_size
        stmt = (
            select(Embedding)
            .options(defer(Embedding.embedding))
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
    async def paginate_by_source(
        db: AsyncSession,
        *,
        category: Optional[str] = None,
        keyword: Optional[str] = None,
        page_num: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[str], int]:
        """按 source_id 分组分页（返回当前页的 source_id 列表 + 文档总数）。"""
        from sqlalchemy import distinct

        conds = [Embedding.source_id.isnot(None)]
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

        # 文档总数（distinct source_id）
        count_stmt = select(func.count(distinct(Embedding.source_id))).where(
            and_(*conds)
        )
        count_result = await db.execute(count_stmt)
        total = int(count_result.scalar_one() or 0)

        # 分页取 source_id（按最新创建排序）
        offset = (page_num - 1) * page_size
        source_stmt = (
            select(Embedding.source_id, func.max(Embedding.created_at).label("latest"))
            .where(and_(*conds))
            .group_by(Embedding.source_id)
            .order_by(func.max(Embedding.created_at).desc())
            .offset(offset)
            .limit(page_size)
        )
        if keyword:
            source_stmt = source_stmt.having(
                func.bool_or(
                    or_(
                        Embedding.title.ilike(f"%{keyword}%"),
                        Embedding.content.ilike(f"%{keyword}%"),
                    )
                )
            )
        result = await db.execute(source_stmt)
        source_ids = [row[0] for row in result.all()]

        return source_ids, total

    @staticmethod
    async def get_chunks_by_source_ids(
        db: AsyncSession,
        source_ids: List[str],
    ) -> List[Embedding]:
        """批量获取多个 source_id 的所有 chunks。"""
        if not source_ids:
            return []
        stmt = (
            select(Embedding)
            .options(defer(Embedding.embedding))
            .where(Embedding.source_id.in_(source_ids))
            .order_by(Embedding.source_id, Embedding.chunk_index.asc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_category_stats(db: AsyncSession) -> dict:
        """获取各分类的统计信息。"""
        stmt = select(Embedding.category, func.count(Embedding.id)).group_by(
            Embedding.category
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
    async def delete_by_source_id(
        db: AsyncSession,
        source_id: str,
    ) -> int:
        """按 source_id 删除该来源的所有 chunks。"""
        stmt = delete(Embedding).where(Embedding.source_id == source_id)
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

    # ---------- 向量搜索 ----------

    @staticmethod
    async def vector_search(
        db: AsyncSession,
        query_vector: List[float],
        *,
        category: Optional[str] = None,
        top_k: int = 5,
    ) -> List[dict]:
        """使用 pgvector 余弦距离在数据库层完成向量检索。"""
        from sqlalchemy import text

        # 避免 Python str(list) 对极小值使用科学记号（pgvector 无法解析）
        vec_str = "[" + ",".join(f"{v:.10f}" for v in query_vector) + "]"

        sql = """
            SELECT id, source_id, chunk_index, title, content, category,
                   1 - (embedding <=> :query_vector::vector) AS score
            FROM embeddings
            WHERE embedding IS NOT NULL
        """
        params: dict = {"query_vector": vec_str, "top_k": top_k}

        if category:
            sql += " AND category = :category"
            params["category"] = category

        sql += " ORDER BY embedding <=> :query_vector::vector LIMIT :top_k"

        result = await db.execute(text(sql), params)
        rows = result.mappings().all()

        return [
            {
                "id": row["id"],
                "source_id": row["source_id"],
                "chunk_index": row["chunk_index"],
                "title": row["title"],
                "content": row["content"],
                "category": row["category"],
                "score": float(row["score"]),
            }
            for row in rows
        ]

    # ---------- 事务辅助 ----------

    @staticmethod
    async def commit(db: AsyncSession) -> None:
        await db.commit()

    @staticmethod
    async def refresh(db: AsyncSession, obj: Embedding) -> None:
        await db.refresh(obj)


__all__ = ["EmbeddingRepository"]
