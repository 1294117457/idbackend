"""Embedding 服务（Layer 2）

职责：
- 向量 upsert / search
- CRUD 业务方法（管理端）

工具方法已下沉到 infra 层：
- 文件解析: src.infra.file_parser
- 文本切块: src.infra.ai.text_splitter
- 向量生成: src.infra.ai.model
"""

import uuid
import logging
from typing import List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from src.infra.ai import embed_text, embed_texts
from src.infra.ai.text_splitter import split_text
from src.models.embedding import Embedding, EmbeddingCategory
from src.repositories.embedding_repo import EmbeddingRepository
from src.app.schemas.embedding import (
    EmbeddingUploadRequest,
    EmbeddingUpdateRequest,
    EmbeddingQueryRequest,
    EmbeddingDeleteRequest,
    EmbeddingSearchRequest,
    EmbeddingVO,
    EmbeddingDetailVO,
    EmbeddingSearchResultVO,
    EmbeddingUploadResultVO,
    EmbeddingDeleteResultVO,
    EmbeddingStatsVO,
    EmbeddingListVO,
    EmbeddingSearchListVO,
    Page,
)

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Embedding 服务（Layer 2）"""

    # ─────────────────────────────────────────────────────────────────────────
    # 核心：多 chunk 存储
    # ─────────────────────────────────────────────────────────────────────────

    async def upsert(
        self,
        db: AsyncSession,
        *,
        title: Optional[str],
        content: str,
        category: str,
        source_id: Optional[str] = None,
    ) -> Tuple[str, int]:

        chunks = split_text(content)
        if not chunks:
            raise ValueError(f"内容为空、解析失败或全部被过滤（< {50} 字符）: {title}")

        if source_id is None:
            source_id = f"doc_{uuid.uuid4().hex[:12]}"

        vectors = await embed_texts(chunks)

        # L2 归一化：消除向量模长差异，确保余弦相似度计算稳定
        import numpy as np
        vectors = [
            (np.array(v, dtype=np.float32) / max(np.linalg.norm(v), 1e-8)).tolist()
            for v in vectors
        ]

        # 先删旧 chunks（同一来源覆盖写入）
        await EmbeddingRepository.delete_by_source_id(db, source_id)

        for idx, (chunk, vector) in enumerate(zip(chunks, vectors)):
            embedding = Embedding(
                source_id=source_id,
                chunk_index=idx,
                title=title,
                content=chunk,
                category=category,
                embedding=vector,
            )
            db.add(embedding)

        await db.flush()
        await db.commit()

        logger.info(f"入库: source_id={source_id}, title={title}, chunks={len(chunks)}")
        return source_id, len(chunks)

    async def upsert_by_template(
        self,
        db: AsyncSession,
        *,
        title: Optional[str],
        content: str,
        template_id: int,
    ) -> None:
        """模板同步入库（source_id = tpl_{template_id}）。"""
        await self.upsert(
            db,
            title=title,
            content=content,
            category=EmbeddingCategory.TEMPLATE.value,
            source_id=f"tpl_{template_id}",
        )

    async def delete_by_template(
        self,
        db: AsyncSession,
        template_id: int,
    ) -> int:
        """删除模板对应的所有 chunks。"""
        return await self.delete_by_source(db, f"tpl_{template_id}")

    async def delete_by_source(
        self,
        db: AsyncSession,
        source_id: str,
    ) -> int:
        """按 source_id 删除某来源的所有 chunks。"""
        count = await EmbeddingRepository.delete_by_source_id(db, source_id)
        await EmbeddingRepository.commit(db)
        return count

    # ─────────────────────────────────────────────────────────────────────────
    # 搜索方法（vector / bm25 / rrf）
    # ─────────────────────────────────────────────────────────────────────────

    async def vector_search(
        self,
        db: AsyncSession,
        query: str,
        *,
        category: Optional[str] = None,
        top_k: Optional[int] = None,
    ) -> List[dict]:

        from src.infra.config import get_rag_config
        rag_cfg = get_rag_config()

        if top_k is None:
            top_k = rag_cfg.get("top_k", 5)

        query_vector = await embed_text(query)
        hits = await EmbeddingRepository.vector_search(
            db,
            query_vector,
            category=category,
            top_k=top_k,
        )

        return hits

    async def bm25_search(
        self,
        db: AsyncSession,
        query: str,
        *,
        category: Optional[str] = None,
        top_k: Optional[int] = None,
    ) -> List[dict]:

        from src.infra.config import get_rag_config
        rag_cfg = get_rag_config()

        if top_k is None:
            top_k = rag_cfg.get("top_k", 5)

        hits = await EmbeddingRepository.bm25_search(
            db,
            query,
            category=category,
            top_k=top_k,
        )

        return hits

    async def rrf_search(
        self,
        db: AsyncSession,
        query: str,
        *,
        category: Optional[str] = None,
        top_k: Optional[int] = None,
    ):
        """混合检索（向量 + BM25 → RFF 融合），返回 FusionResult。"""
        from src.infra.config import get_rag_config
        from src.infra.ai.retrieval_processor import RetrievalProcessor, SearchHit

        rag_cfg = get_rag_config()

        if top_k is None:
            top_k = rag_cfg.get("top_k", 5)

        candidate_k_cfg = rag_cfg.get("candidate_k")
        candidate_k = candidate_k_cfg if candidate_k_cfg else max(top_k * 6, top_k + 15)

        query_vector = await embed_text(query)

        raw_vector_hits = await EmbeddingRepository.vector_search(
            db, query_vector, category=category, top_k=candidate_k
        )
        raw_bm25_hits = await EmbeddingRepository.bm25_search(
            db, query, category=category, top_k=candidate_k
        )

        # 读取 RAG 配置（融合权重 / 衰减 / 阈值）
        same_doc_decay = rag_cfg.get("same_doc_decay", 0.7)
        vector_weight = rag_cfg.get("vector_weight", 1.0)
        bm25_weight = rag_cfg.get("bm25_weight", 1.0)
        single_source_penalty = rag_cfg.get("single_source_penalty", 0.5)
        min_final_score = rag_cfg.get("min_score", 0.05)
        normalize_scores = rag_cfg.get("normalize_scores", True)

        processor = RetrievalProcessor()

        # 各路分别：归一化 + 同文档衰减 + 乘权重
        vec_hits = processor.single_process(
            raw_vector_hits,
            source="vector",
            weight=vector_weight,
            same_doc_decay=same_doc_decay,
            normalize=False,
            score_field="raw_score",
        )
        bm25_hits = processor.single_process(
            raw_bm25_hits,
            source="bm25",
            weight=bm25_weight,
            same_doc_decay=same_doc_decay,
            normalize=True,
            score_field="raw_score",
        )

        # 双路融合
        fusion_result = processor.multi_process(
            vec_hits,
            bm25_hits,
            vector_weight=vector_weight,
            bm25_weight=bm25_weight,
            same_doc_decay=same_doc_decay,
            single_source_penalty=single_source_penalty,
            min_score=min_final_score,
            normalize_scores=normalize_scores,
            query=query,
        )

        # 截断 top_k
        fusion_result.hits = fusion_result.hits[:top_k]

        return fusion_result

    # ═══════════════════════════════════════════════════════════════════════════
    # 管理端 API（上传/删除/查询）
    # ═══════════════════════════════════════════════════════════════════════════

    async def upload(
        self,
        db: AsyncSession,
        request: EmbeddingUploadRequest,
    ) -> EmbeddingUploadResultVO:
        request.validate_category()

        source_id, chunk_count = await self.upsert(
            db,
            title=request.title,
            content=request.content,
            category=request.category,
        )

        return EmbeddingUploadResultVO.from_upload(
            source_id=source_id,
            title=request.title,
            category=request.category,
            chunk_count=chunk_count,
        )

    async def update(
        self,
        db: AsyncSession,
        embedding_id: int,
        request: EmbeddingUpdateRequest,
    ) -> Optional[EmbeddingVO]:
        """更新单个 chunk（仅更新文本，向量重新生成）"""
        embedding = await EmbeddingRepository.get_by_id(db, embedding_id)
        if not embedding:
            return None

        if request.title is not None:
            embedding.title = request.title
        if request.content is not None:
            embedding.content = request.content
            vector = await embed_text(request.content)
            embedding.embedding = vector

        await EmbeddingRepository.update(db, embedding)
        await EmbeddingRepository.commit(db)

        return EmbeddingVO.from_orm_to_vo(embedding)

    async def delete(
        self,
        db: AsyncSession,
        request: EmbeddingDeleteRequest,
    ) -> EmbeddingDeleteResultVO:
        """批量删除 embedding（按 ID）"""
        deleted_count = await EmbeddingRepository.delete_by_ids(db, request.ids)
        await EmbeddingRepository.commit(db)

        return EmbeddingDeleteResultVO(
            deletedCount=deleted_count,
            totalRequested=len(request.ids),
        )

    async def list_(
        self,
        db: AsyncSession,
        request: EmbeddingQueryRequest,
    ):
        """分页查询（按文档分组，树形结构）"""
        from src.app.schemas.embedding import EmbeddingDocVO, EmbeddingDocListVO

        source_ids, total = await EmbeddingRepository.paginate_by_source(
            db,
            category=request.category,
            keyword=request.keyword,
            page_num=request.page_num,
            page_size=request.page_size,
        )

        chunks = await EmbeddingRepository.get_chunks_by_source_ids(db, source_ids)

        # 按 source_id 分组
        from collections import OrderedDict
        doc_map: OrderedDict[str, list] = OrderedDict()
        for sid in source_ids:
            doc_map[sid] = []
        for chunk in chunks:
            if chunk.source_id in doc_map:
                doc_map[chunk.source_id].append(chunk)

        docs = [
            EmbeddingDocVO.from_source_group(sid, chunk_list)
            for sid, chunk_list in doc_map.items()
            if chunk_list
        ]

        return Page.from_list_to_page(docs, total, request.page_num, request.page_size)

    async def get_detail(
        self,
        db: AsyncSession,
        embedding_id: int,
    ) -> Optional[EmbeddingDetailVO]:
        """获取 embedding 详情（含向量）"""
        embedding = await EmbeddingRepository.get_by_id(db, embedding_id)
        if not embedding:
            return None
        return EmbeddingDetailVO.from_orm_to_vo(embedding, include_vector=True)

    async def search_(
        self,
        db: AsyncSession,
        request: EmbeddingSearchRequest,
    ) -> EmbeddingSearchListVO:
        """混合检索（向量 + BM25 → RFF 融合）"""
        fusion_result = await self.rrf_search(
            db,
            query=request.query,
            category=request.category,
        )

        # SearchHit → EmbeddingSearchResultVO
        hits_vo = [
            EmbeddingSearchResultVO(
                id=int(hit.chunk_id) if hit.chunk_id.isdigit() else 0,
                sourceId=hit.source_id,
                chunkIndex=hit.metadata.get("chunk_index"),
                title=hit.metadata.get("title"),
                content=hit.content,
                category=hit.metadata.get("category", ""),
                categoryText=hit.metadata.get("category_text", ""),
                vectorScore=round(hit.vector_score, 6),
                bm25Score=round(hit.bm25_score, 6),
                normVectorScore=round(hit.norm_vector_score, 6),
                normBm25Score=round(hit.norm_bm25_score, 6),
                fusedScore=round(hit.fused_score, 6),
                isVectorHit=hit.is_vector_hit,
                isBm25Hit=hit.is_bm25_hit,
            )
            for hit in fusion_result.hits
        ]

        return EmbeddingSearchListVO(
            list=hits_vo,
            config=fusion_result.config,
            query=fusion_result.query,
            totalTimeMs=fusion_result.total_time_ms,
        )

    async def get_stats(self, db: AsyncSession) -> EmbeddingStatsVO:
        """获取统计信息"""
        total = await EmbeddingRepository.count_all(db)
        category_stats = await EmbeddingRepository.get_category_stats(db)

        return EmbeddingStatsVO(
            totalCount=total,
            categoryStats=category_stats,
        )


# 全局单例
_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """获取 EmbeddingService 单例。"""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
