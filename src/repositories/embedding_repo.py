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

        sql = """
            SELECT id, source_id, chunk_index, title, content, category,
                   1 - (embedding <=> :query_vector) AS score
            FROM embeddings
            WHERE embedding IS NOT NULL
        """
        params: dict = {"query_vector": str(query_vector)}

        if category:
            sql += " AND category = :category"
            params["category"] = category

        sql += f" ORDER BY embedding <=> :query_vector LIMIT {top_k}"

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

    @staticmethod
    async def bm25_search(
        db: AsyncSession,
        query: str,
        *,
        category: Optional[str] = None,
        top_k: int = 5,
    ) -> List[dict]:
        """BM25 风格的中文全文检索（zhparser + ts_rank）。

        与 vector_search 的区别：
          - vector_search: 语义相似度（依赖 embedding 模型理解）
          - bm25_search:  精确关键词匹配（依赖 zhparser 分词 + tsvector GIN 索引）

        适合：用户检索具体术语、政策名称、编号、专有名词等。
        """
        from sqlalchemy import text

        sql = """
            SELECT id, source_id, chunk_index, title, content, category,
                   ts_rank_cd(content_tsv,
                       plainto_tsquery('chinese_zh', :query)
                   ) AS bm25_score
            FROM embeddings
            WHERE content_tsv @@ plainto_tsquery('chinese_zh', :query)
        """
        params: dict = {"query": query}

        if category:
            sql += " AND category = :category"
            params["category"] = category

        sql += " ORDER BY bm25_score DESC LIMIT " + str(int(top_k))

        result = await db.execute(text(sql), params)
        rows = result.mappings().all()

        return [
            {
                "id": r["id"],
                "source_id": r["source_id"],
                "chunk_index": r["chunk_index"],
                "title": r["title"],
                "content": r["content"],
                "category": r["category"],
                "score": float(r["bm25_score"] or 0),
            }
            for r in rows
        ]

    @staticmethod
    async def rrf_search(
        db: AsyncSession,
        query: str,
        query_vector: List[float],
        *,
        category: Optional[str] = None,
        top_k: int = 5,
        candidate_k: Optional[int] = None,
        rrf_k: int = 60,
    ) -> List[dict]:
        """RRF（Reciprocal Rank Fusion）混合检索：向量 + BM25。

        流程：
          1. 向量取 candidate_k 候选（默认 2 * top_k）
          2. BM25 取 candidate_k 候选（默认 2 * top_k）
          3. 按 chunk id 合并去重，按 RRF 公式打分：
                 rrf_score = Σ_r  1 / (rrf_k + rank_r)
             即两路排名相加；对只出现在一路的项，对应路该项为 0。
          4. 按 rrf_score 降序取 top_k 返回。

        优点：
          - 不需要分数归一化（不依赖余弦距离和 ts_rank 的可比性）
          - 单边高排名也能拿满分；双路同时命中 = 强证据
          - candidate_k 越大召回越好，top_k 越大越稳
        """
        if candidate_k is None:
            candidate_k = max(top_k * 2, top_k + 5)

        # 1) 两路并发拉候选；这里顺序执行（asyncio.gather 也可，sqlalchemy 同步 exec）
        vector_hits = await EmbeddingRepository.vector_search(
            db, query_vector, category=category, top_k=candidate_k
        )
        bm25_hits = await EmbeddingRepository.bm25_search(
            db, query, category=category, top_k=candidate_k
        )

        # 2) 按 id 构建 RRF 评分表
        fused: dict = {}

        for rank, hit in enumerate(vector_hits, start=1):
            chunk_id = hit["id"]
            fused[chunk_id] = {
                **hit,                       # 保留全部原始字段
                "_rrf_score": 1.0 / (rrf_k + rank),
                "_vector_rank": rank,
                "_bm25_rank": None,
                "_sources": ["vector"],
            }

        for rank, hit in enumerate(bm25_hits, start=1):
            chunk_id = hit["id"]
            bm25_contrib = 1.0 / (rrf_k + rank)
            if chunk_id in fused:
                fused[chunk_id]["_rrf_score"] += bm25_contrib
                fused[chunk_id]["_bm25_rank"] = rank
                fused[chunk_id]["_sources"].append("bm25")
            else:
                fused[chunk_id] = {
                    **hit,
                    "_rrf_score": bm25_contrib,
                    "_vector_rank": None,
                    "_bm25_rank": rank,
                    "_sources": ["bm25"],
                }

        # 3) 排序 + 截断
        ranked = sorted(fused.values(), key=lambda x: x["_rrf_score"], reverse=True)
        top_hits = ranked[:top_k]

        # 4) 投影成对外统一形态
        return [
            {
                "id": h["id"],
                "source_id": h["source_id"],
                "chunk_index": h["chunk_index"],
                "title": h["title"],
                "content": h["content"],
                "category": h["category"],
                # 对外仍暴露一个 score 字段，融合分数（按 [0, 2/rrf_k] 范围）
                "score": float(h["_rrf_score"]),
                "rrf_score": float(h["_rrf_score"]),
                "vector_rank": h["_vector_rank"],
                "bm25_rank": h["_bm25_rank"],
                "sources": h["_sources"],
            }
            for h in top_hits
        ]

    # ---------- 事务辅助 ----------

    @staticmethod
    async def commit(db: AsyncSession) -> None:
        await db.commit()

    @staticmethod
    async def refresh(db: AsyncSession, obj: Embedding) -> None:
        await db.refresh(obj)


__all__ = ["EmbeddingRepository"]
