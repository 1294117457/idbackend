"""Embedding DTO / VO 定义

职责：
- Request DTO：接收前端请求参数
- Response VO：返回给前端的结构化数据
- 转换方法：ORM → VO（to_vo 类方法）
"""
from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field, ConfigDict

from src.models.embedding import EmbeddingCategory, Embedding as EmbeddingModel
from src.app.schemas.page import Page


# ═══════════════════════════════════════════════════════════════════════════════
# Request DTO
# ═══════════════════════════════════════════════════════════════════════════════


class EmbeddingUploadRequest(BaseModel):
    """Embedding 上传请求 DTO"""
    model_config = ConfigDict(populate_by_name=True)

    title: str = Field(..., min_length=1, max_length=200, description="标题")
    content: str = Field(..., min_length=1, description="内容原文")
    category: str = Field(..., description="分类：POLICY / SYSTEM_GUIDE / TEMPLATE / FAQ")

    def validate_category(self) -> str:
        """校验并返回合法的 category 值"""
        valid = [e.value for e in EmbeddingCategory]
        if self.category not in valid:
            raise ValueError(f"无效的 category，可选值：{valid}")
        return self.category


class EmbeddingUpdateRequest(BaseModel):
    """Embedding 更新请求 DTO"""
    model_config = ConfigDict(populate_by_name=True)

    title: Optional[str] = Field(default=None, max_length=200, description="标题")
    content: Optional[str] = Field(default=None, min_length=1, description="内容原文")


class EmbeddingQueryRequest(BaseModel):
    """Embedding 查询请求 DTO"""
    model_config = ConfigDict(populate_by_name=True)

    category: Optional[str] = Field(default=None, description="分类过滤")
    keyword: Optional[str] = Field(default=None, description="关键词模糊搜索（标题/内容）")
    page_num: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=20, ge=1, le=100, description="每页大小")


class EmbeddingDeleteRequest(BaseModel):
    """Embedding 删除请求 DTO"""
    model_config = ConfigDict(populate_by_name=True)

    ids: List[int] = Field(..., min_length=1, description="待删除的 embedding ID 列表")


class EmbeddingSearchRequest(BaseModel):
    """Embedding 搜索请求 DTO"""
    model_config = ConfigDict(populate_by_name=True)

    query: str = Field(..., min_length=1, description="搜索查询文本")
    category: Optional[str] = Field(default=None, description="分类过滤")
    # top_k 从 config.py 统一读取，不从前端请求获取


# ═══════════════════════════════════════════════════════════════════════════════
# Response VO
# ═══════════════════════════════════════════════════════════════════════════════


def _category_text(category: str) -> str:
    """Category → 中文文本"""
    return {
        EmbeddingCategory.POLICY.value: "政策文件",
        EmbeddingCategory.SYSTEM_GUIDE.value: "系统指南",
        EmbeddingCategory.TEMPLATE.value: "模板",
        EmbeddingCategory.FAQ.value: "常见问题",
    }.get(category, "未知")


class EmbeddingChunkVO(BaseModel):
    """单个 chunk VO（树形子节点）"""
    id: int
    chunkIndex: int = 0
    content: str
    createdAt: Optional[str] = None

    @classmethod
    def from_orm(cls, emb: EmbeddingModel) -> "EmbeddingChunkVO":
        return cls(
            id=emb.id,
            chunkIndex=emb.chunk_index or 0,
            content=emb.content,
            createdAt=emb.created_at.isoformat() if emb.created_at else None,
        )


class EmbeddingDocVO(BaseModel):
    """文档级 VO（树形父节点，按 source_id 分组）"""
    sourceId: str
    title: Optional[str] = None
    category: str
    categoryText: str
    chunkCount: int = 0
    createdAt: Optional[str] = None
    children: List[EmbeddingChunkVO] = []

    @classmethod
    def from_source_group(
        cls,
        source_id: str,
        chunks: List[EmbeddingModel],
    ) -> "EmbeddingDocVO":
        """一组同 source 的 chunks → DocVO（树形父节点）

        约定：
        - chunks 至少 1 条（service 已在 list_ 中过滤空组）
        - 用第一个 chunk 的 title / category / createdAt 作为文档级元数据
        """
        first = chunks[0]
        return cls(
            sourceId=source_id,
            title=first.title,
            category=first.category,
            categoryText=_category_text(first.category),
            chunkCount=len(chunks),
            createdAt=first.created_at.isoformat() if first.created_at else None,
            children=[EmbeddingChunkVO.from_orm(c) for c in chunks],
        )


class EmbeddingVO(BaseModel):
    """Embedding 列表项 VO（扁平，用于详情等场景）"""
    id: int
    sourceId: Optional[str] = None
    chunkIndex: Optional[int] = None
    title: Optional[str] = None
    content: str
    category: str
    categoryText: str
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None

    @classmethod
    def from_orm_to_vo(cls, emb: EmbeddingModel) -> "EmbeddingVO":
        return cls(
            id=emb.id,
            sourceId=emb.source_id,
            chunkIndex=emb.chunk_index,
            title=emb.title,
            content=emb.content,
            category=emb.category,
            categoryText=_category_text(emb.category),
            createdAt=emb.created_at.isoformat() if emb.created_at else None,
            updatedAt=emb.updated_at.isoformat() if emb.updated_at else None,
        )


class EmbeddingDetailVO(EmbeddingVO):
    """Embedding 详情 VO（含向量，调试用）"""
    embedding: Optional[List[float]] = None

    @classmethod
    def from_orm_to_vo(cls, emb: EmbeddingModel, include_vector: bool = False) -> "EmbeddingDetailVO":
        vo = super().from_orm_to_vo(emb)
        if include_vector:
            vo.embedding = emb.embedding
        return vo


class EmbeddingSearchResultVO(BaseModel):
    """Embedding 搜索结果 VO"""
    id: int
    sourceId: Optional[str] = None
    chunkIndex: Optional[int] = None
    title: Optional[str] = None
    content: str
    category: str
    categoryText: str

    # 原始分数
    vectorScore: float = 0.0
    bm25Score: float = 0.0

    # 归一化分数
    normVectorScore: float = 0.0
    normBm25Score: float = 0.0

    # 融合分数
    fusedScore: float = 0.0

    # 来源标识
    isVectorHit: bool = False
    isBm25Hit: bool = False

    @classmethod
    def from_search_hit(cls, hit: dict) -> "EmbeddingSearchResultVO":
        """SearchHit dict → VO（最终返回给前端的结构）"""
        return cls(
            id=int(hit.get("id", 0)),
            sourceId=hit.get("source_id"),
            chunkIndex=hit.get("chunk_index"),
            title=hit.get("title"),
            content=hit.get("content", ""),
            category=hit.get("category", ""),
            categoryText=_category_text(hit.get("category", "")),
            vectorScore=round(hit.get("vectorScore", 0.0), 6),
            bm25Score=round(hit.get("bm25Score", 0.0), 6),
            normVectorScore=round(hit.get("normVectorScore", 0.0), 6),
            normBm25Score=round(hit.get("normBm25Score", 0.0), 6),
            fusedScore=round(hit.get("fusedScore", 0.0), 6),
            isVectorHit=hit.get("isVectorHit", False),
            isBm25Hit=hit.get("isBm25Hit", False),
        )


class EmbeddingSearchListVO(BaseModel):
    """Embedding 搜索结果 VO（携带配置和统计信息）"""
    list: List[EmbeddingSearchResultVO]
    config: Dict[str, Any] = Field(default_factory=dict, description="本次搜索使用的配置")
    query: str = ""
    totalTimeMs: float = 0.0


class EmbeddingUploadResultVO(BaseModel):
    """Embedding 上传结果 VO"""
    sourceId: str = Field(..., description="来源 ID")
    title: str
    category: str
    categoryText: str
    chunkCount: int = Field(..., description="拆分的 chunk 数量")

    @classmethod
    def from_upload(cls, source_id: str, title: str, category: str, chunk_count: int) -> "EmbeddingUploadResultVO":
        return cls(
            sourceId=source_id,
            title=title,
            category=category,
            categoryText=_category_text(category),
            chunkCount=chunk_count,
        )


class EmbeddingDeleteResultVO(BaseModel):
    """Embedding 删除结果 VO"""
    deletedCount: int = Field(..., description="实际删除的数量")
    totalRequested: int = Field(..., description="请求删除的数量")


class EmbeddingStatsVO(BaseModel):
    """Embedding 统计信息 VO"""
    totalCount: int = Field(..., description="总记录数")
    categoryStats: dict = Field(..., description="各分类的统计")


class EmbeddingDocListVO(Page[EmbeddingDocVO]):
    """Embedding 文档级分页查询结果（树形）"""
    pass


class EmbeddingListVO(Page[EmbeddingVO]):
    """Embedding 分页查询结果（扁平）"""
    pass


__all__ = [
    "EmbeddingUploadRequest",
    "EmbeddingUpdateRequest",
    "EmbeddingQueryRequest",
    "EmbeddingDeleteRequest",
    "EmbeddingSearchRequest",
    "EmbeddingChunkVO",
    "EmbeddingDocVO",
    "EmbeddingVO",
    "EmbeddingDetailVO",
    "EmbeddingSearchResultVO",
    "EmbeddingUploadResultVO",
    "EmbeddingDeleteResultVO",
    "EmbeddingStatsVO",
    "EmbeddingDocListVO",
    "EmbeddingListVO",
    "EmbeddingSearchListVO",
]
