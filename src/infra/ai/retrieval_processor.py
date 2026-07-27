"""Retrieval 命中结果处理器

职责：
- 对检索命中结果（vector / bm25）做后处理
- 流水线：归一化 → 同文档衰减 → 乘权重（单路）→ 融合 + 阈值过滤（双路）
- 不涉及数据库 / 模型调用，纯粹是分数处理工具

使用方式：
    processor = RetrievalProcessor()
    vec_hits = processor.single_process(raw_vec_hits, source="vector", ...)
    bm25_hits = processor.single_process(raw_bm25_hits, source="bm25", ...)
    result = processor.multi_process(
        vec_hits, bm25_hits,
        vector_weight=1.0,
        bm25_weight=1.0,
        same_doc_decay=0.7,
        single_source_penalty=0.5,
        min_score=0.05,
    )
    # result 是 FusionResult，携带 hits + config + 统计信息
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any


@dataclass
class SearchHit:
    """单条检索命中（融合前/后通用）"""
    chunk_id: str
    content: str
    source_id: str

    # 原始分数（来自数据库）
    vector_score: float = 0.0
    bm25_score: float = 0.0

    # 归一化分数
    norm_vector_score: float = 0.0
    norm_bm25_score: float = 0.0

    # 融合分数
    fused_score: float = 0.0

    # 来源标识
    is_vector_hit: bool = False
    is_bm25_hit: bool = False

    # 数据库原始元信息（processor 不关心，前端展示用）
    metadata: Dict[str, Any] = field(default_factory=dict)

    # 内部：原始排名（仅供调试）
    _vector_rank: Optional[int] = None
    _bm25_rank: Optional[int] = None


@dataclass
class FusionResult:
    """双路融合结果 VO"""
    hits: List[SearchHit]
    config: Dict[str, Any]
    query: str = ""

    total_time_ms: float = 0.0


class RetrievalProcessor:
    """检索命中融合处理器。

    两段式流水线：
    1. single_process：单路独立处理（归一化 + 同文档衰减 + 权重）
    2. multi_process：双路融合（单路折扣 + 加和 + 阈值过滤）
    """

    # ─────────────────────────────────────────────────────────────────────────
    # 单路处理
    # ─────────────────────────────────────────────────────────────────────────

    def single_process(
        self,
        raw_hits: List[Dict],
        *,
        source: str = "vector",
        weight: float = 1.0,
        same_doc_decay: Optional[float] = None,
        normalize: bool = True,
        score_field: str = "score",
        doc_field: str = "source_id",
    ) -> List[SearchHit]:
        """对单路命中做归一化 + 同文档衰减 + 权重。

        Args:
            raw_hits: 命中结果列表，每个元素必须包含 score_field 字段
            source: 来源标识，"vector" 或 "bm25"
            weight: 最终权重，乘在归一化 + 衰减之后（默认 1.0 不变）
            same_doc_decay: 同文档衰减系数（第 N 个 chunk 乘以 decay^(N-1)），
                           为 None 或 >= 1.0 表示不衰减
            normalize: 是否做 Min-Max 归一化（默认 True）；关闭时直接用原始分
            score_field: 原始分数字段名（默认 "score"）
            doc_field: 用于分组的文档标识字段（默认 "source_id"）

        Returns:
            List[SearchHit]，按命中顺序排列
        """
        if not raw_hits:
            return []

        # 1. 归一化
        if normalize:
            raw_scores = [h.get(score_field, 0.0) for h in raw_hits]
            norm_scores = _min_max_normalize(raw_scores)
        else:
            norm_scores = [h.get(score_field, 0.0) for h in raw_hits]

        # 2. 同文档衰减（按 doc_field 内出现顺序，从第 2 个开始衰减）
        if same_doc_decay is not None and same_doc_decay < 1.0:
            doc_seen: Dict[str, int] = {}
            for i, (h, norm) in enumerate(zip(raw_hits, norm_scores)):
                doc_key = h.get(doc_field, "")
                doc_seen[doc_key] = doc_seen.get(doc_key, 0) + 1
                n = doc_seen[doc_key]
                if n > 1:
                    norm_scores[i] = norm * (same_doc_decay ** (n - 1))

        # 3. 乘权重
        if weight != 1.0:
            norm_scores = [s * weight for s in norm_scores]

        # 4. 构建 SearchHit（metadata 透传数据库原始字段）
        is_vector = source == "vector"
        hits: List[SearchHit] = []
        for h, norm in zip(raw_hits, norm_scores):
            # metadata 透传 title/category/chunk_index 等，供前端展示
            metadata = h.get("metadata", {}) if isinstance(h.get("metadata"), dict) else {}
            if not metadata:
                metadata = {
                    "chunk_index": h.get("chunk_index"),
                    "title": h.get("title"),
                    "category": h.get("category"),
                    "category_text": {
                        "POLICY": "政策文件",
                        "SYSTEM_GUIDE": "系统指南",
                        "TEMPLATE": "模板",
                        "FAQ": "常见问题",
                    }.get(h.get("category", ""), "未知"),
                }
            hit = SearchHit(
                chunk_id=str(h.get("id", "")),
                content=h.get("content", ""),
                source_id=h.get("source_id", ""),
                vector_score=h.get(score_field, 0.0) if is_vector else 0.0,
                bm25_score=h.get(score_field, 0.0) if not is_vector else 0.0,
                norm_vector_score=norm if is_vector else 0.0,
                norm_bm25_score=norm if not is_vector else 0.0,
                is_vector_hit=is_vector,
                is_bm25_hit=not is_vector,
                metadata=metadata,
            )
            hits.append(hit)

        return hits

    # ─────────────────────────────────────────────────────────────────────────
    # 双路融合
    # ─────────────────────────────────────────────────────────────────────────

    def multi_process(
        self,
        vec_hits: List[SearchHit],
        bm25_hits: List[SearchHit],
        *,
        vector_weight: float = 1.0,
        bm25_weight: float = 1.0,
        same_doc_decay: float = 0.7,
        single_source_penalty: float = 0.5,
        min_score: Optional[float] = None,
        normalize_scores: bool = True,
        query: str = "",
    ) -> FusionResult:
        """对两路命中做双路融合：归一化 + 单路折扣 + 加和 + 阈值过滤。

        融合规则：
          - 双路命中：norm_vec + norm_bm25
          - 单路命中：norm * single_source_penalty

        Args:
            vec_hits: 向量检索结果（已过 single_process）
            bm25_hits: BM25 检索结果（已过 single_process）
            vector_weight: 向量路权重
            bm25_weight: BM25 路权重
            same_doc_decay: 同文档衰减系数
            single_source_penalty: 单路命中折扣系数
            min_score: 最低最终分门槛，低于此分直接丢弃；None 不过滤
            normalize_scores: 是否对各路做归一化
            query: 查询语句（透传到 FusionResult）

        Returns:
            FusionResult：携带融合结果 + 配置 + 统计信息
        """
        import time
        start = time.perf_counter()

        # 用 chunk_id 做 key，去重 + 融合
        fused_map: Dict[str, SearchHit] = {}
        vec_ranks: Dict[str, int] = {}
        bm25_ranks: Dict[str, int] = {}

        # 记录原始排名
        for rank, hit in enumerate(vec_hits, start=1):
            vec_ranks[hit.chunk_id] = rank
        for rank, hit in enumerate(bm25_hits, start=1):
            bm25_ranks[hit.chunk_id] = rank

        # 放入 vector 一路
        for hit in vec_hits:
            fused_map[hit.chunk_id] = SearchHit(
                chunk_id=hit.chunk_id,
                content=hit.content,
                source_id=hit.source_id,
                vector_score=hit.vector_score,
                bm25_score=0.0,
                norm_vector_score=hit.norm_vector_score,
                norm_bm25_score=0.0,
                is_vector_hit=True,
                is_bm25_hit=False,
                metadata=hit.metadata,
                _vector_rank=vec_ranks.get(hit.chunk_id),
            )

        # 叠加 bm25 一路
        for hit in bm25_hits:
            cid = hit.chunk_id
            if cid in fused_map:
                existing = fused_map[cid]
                existing.bm25_score = hit.bm25_score
                existing.norm_bm25_score = hit.norm_bm25_score
                existing.is_bm25_hit = True
                existing._bm25_rank = bm25_ranks.get(cid)
                # 双路融合分
                existing.fused_score = existing.norm_vector_score + existing.norm_bm25_score
            else:
                fused_map[cid] = SearchHit(
                    chunk_id=hit.chunk_id,
                    content=hit.content,
                    source_id=hit.source_id,
                    vector_score=0.0,
                    bm25_score=hit.bm25_score,
                    norm_vector_score=0.0,
                    norm_bm25_score=hit.norm_bm25_score,
                    is_vector_hit=False,
                    is_bm25_hit=True,
                    metadata=hit.metadata,
                    _bm25_rank=bm25_ranks.get(cid),
                )

        # 计算融合分：单路命中乘 penalty
        for hit in fused_map.values():
            if hit.is_vector_hit and hit.is_bm25_hit:
                hit.fused_score = hit.norm_vector_score + hit.norm_bm25_score
            elif hit.is_vector_hit:
                hit.fused_score = hit.norm_vector_score * single_source_penalty
            elif hit.is_bm25_hit:
                hit.fused_score = hit.norm_bm25_score * single_source_penalty

        # 阈值过滤
        all_hits = list(fused_map.values())
        if min_score is not None:
            all_hits = [h for h in all_hits if h.fused_score >= min_score]

        # 按融合分排序
        all_hits.sort(key=lambda x: x.fused_score, reverse=True)

        # 统计
        vector_only = sum(1 for h in all_hits if h.is_vector_hit and not h.is_bm25_hit)
        bm25_only = sum(1 for h in all_hits if h.is_bm25_hit and not h.is_vector_hit)
        both = sum(1 for h in all_hits if h.is_vector_hit and h.is_bm25_hit)

        elapsed_ms = (time.perf_counter() - start) * 1000

        return FusionResult(
            hits=all_hits,
            config={
                "vector_weight": vector_weight,
                "bm25_weight": bm25_weight,
                "same_doc_decay": same_doc_decay,
                "single_source_penalty": single_source_penalty,
                "min_score": min_score,
                "normalize_scores": normalize_scores,
            },
            query=query,
            total_time_ms=round(elapsed_ms, 2),
        )


# ─────────────────────────────────────────────────────────────────────────────
# 内部工具
# ─────────────────────────────────────────────────────────────────────────────

def _min_max_normalize(scores: List[float]) -> List[float]:
    """Min-Max 归一化到 [0, 1]。

    Args:
        scores: 原始分数列表

    Returns:
        归一化后的分数列表（与输入等长）
    """
    if not scores:
        return []
    mn, mx = min(scores), max(scores)
    if mx == mn:
        return [1.0] * len(scores)
    return [(x - mn) / (mx - mn) for x in scores]
