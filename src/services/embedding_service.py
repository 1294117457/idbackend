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
from src.infra.config import get_settings
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
    _category_text,
)

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Embedding 服务（Layer 2）"""

    def __init__(self):
        self.settings = get_settings()

    # ---------- 核心：多 chunk 存储 ----------

    async def upsert(
        self,
        db: AsyncSession,
        *,
        title: Optional[str],
        content: str,
        category: str,
        source_id: Optional[str] = None,
    ) -> Tuple[str, int]:
        """解析文本 → 切块 → 批量生成向量 → 存入数据库（每个 chunk 一行）。

        Args:
            source_id: 指定来源 ID（如 tpl_123）。为 None 时自动生成 doc_xxx。

        Returns:
            (source_id, chunk_count)
        """
        chunks = split_text(content)
        if not chunks:
            raise ValueError(f"内容为空或解析失败: {title}")

        if source_id is None:
            source_id = f"doc_{uuid.uuid4().hex[:12]}"

        vectors = await embed_texts(chunks)

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

    # ---------- 向量搜索 ----------

    async def search(
        self,
        db: AsyncSession,
        query: str,
        *,
        category: Optional[str] = None,
        top_k: int = 5,
    ) -> List[dict]:
        """向量相似度搜索（pgvector SQL 实现）。"""
        query_vector = await embed_text(query)

        return await EmbeddingRepository.vector_search(
            db,
            query_vector,
            category=category,
            top_k=top_k,
        )

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
        from src.app.schemas.embedding import EmbeddingDocVO, EmbeddingChunkVO, EmbeddingDocListVO

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

        docs = []
        for sid, chunk_list in doc_map.items():
            if not chunk_list:
                continue
            first = chunk_list[0]
            docs.append(EmbeddingDocVO(
                sourceId=sid,
                title=first.title,
                category=first.category,
                categoryText=_category_text(first.category),
                chunkCount=len(chunk_list),
                createdAt=first.created_at.isoformat() if first.created_at else None,
                children=[EmbeddingChunkVO.from_orm(c) for c in chunk_list],
            ))

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
        """向量语义搜索"""
        results = await self.search(
            db,
            query=request.query,
            category=request.category,
            top_k=request.top_k,
        )

        vos = [EmbeddingSearchResultVO.from_search_result(r) for r in results]
        total = len(vos)
        return Page.from_list_to_page(vos, total, 1, request.top_k)

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
