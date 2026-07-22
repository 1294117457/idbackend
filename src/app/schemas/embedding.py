"""Embedding DTO / VO 定义

职责：
- Request DTO：接收前端请求参数
- Response VO：返回给前端的结构化数据
- 转换方法：ORM → VO（to_vo 类方法）
"""
from datetime import datetime
from typing import Optional, List

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
    top_k: int = Field(default=5, ge=1, le=50, description="返回数量")


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
    score: float = Field(..., description="相似度分数")

    @classmethod
    def from_search_result(cls, result: dict) -> "EmbeddingSearchResultVO":
        return cls(
            id=result["id"],
            sourceId=result.get("source_id"),
            chunkIndex=result.get("chunk_index"),
            title=result.get("title"),
            content=result["content"],
            category=result["category"],
            categoryText=_category_text(result["category"]),
            score=result["score"],
        )


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


class EmbeddingSearchListVO(Page[EmbeddingSearchResultVO]):
    """Embedding 搜索结果分页"""
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
