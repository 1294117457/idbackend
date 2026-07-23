"""Retrieval 命中结果处理器

职责：
- 对单路检索命中结果（vector / bm25）做统一的后处理
- 流水线：归一化 → 同文档衰减 → 乘权重
- 不涉及数据库 / 模型调用，纯粹是分数处理工具

处理步骤（按顺序）：
1. Min-Max 归一化（normalize）：把原始分数映射到 [0, 1]
2. 同文档衰减（same_doc_decay）：按 source_id 内出现顺序依次衰减
3. 乘权重（weight）：最终加权

每个步骤都是可选的，可通过对应参数控制。
"""

from typing import List, Dict, Optional


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


def process_hits(
    hits: List[Dict],
    *,
    score_field: str = "score",
    target_field: str = "normalized_score",
    normalize: bool = True,
    weight: float = 1.0,
    same_doc_decay: Optional[float] = None,
    doc_field: str = "source_id",
) -> List[Dict]:
    """对单路检索命中结果做后处理（归一化 + 同文档衰减 + 权重）。

    Args:
        hits: 命中结果列表，每个元素必须包含 score_field 字段
        score_field: 原始分数字段名（默认 "score"）
        target_field: 归一化分数写入的字段名（默认 "normalized_score"）
        normalize: 是否做 Min-Max 归一化（默认 True）
        weight: 最终权重（默认 1.0）
        same_doc_decay: 同文档衰减系数（第 N 个 chunk 乘以 decay^(N-1)），
                       为 None 或 1.0 表示不衰减
        doc_field: 用于分组的文档标识字段（默认 "source_id"）

    Returns:
        原地修改后的 hits 列表（也返回方便链式调用）
    """
    if not hits:
        return hits

    # 1. 归一化
    if normalize:
        raw_scores = [h[score_field] for h in hits]
        norm_scores = _min_max_normalize(raw_scores)
        for h, norm in zip(hits, norm_scores):
            h[target_field] = norm
    else:
        for h in hits:
            h[target_field] = h[score_field]

    # 2. 同文档衰减（按 doc_field 内出现顺序，从第 2 个开始衰减）
    if same_doc_decay is not None and same_doc_decay < 1.0:
        doc_seen: Dict[str, int] = {}
        for h in hits:
            doc_key = h.get(doc_field, "")
            doc_seen[doc_key] = doc_seen.get(doc_key, 0) + 1
            n = doc_seen[doc_key]
            if n > 1:
                h[target_field] *= same_doc_decay ** (n - 1)

    # 3. 乘权重
    if weight != 1.0:
        for h in hits:
            h[target_field] *= weight

    return hits


def fuse_hits(
    vector_hits: List[Dict],
    bm25_hits: List[Dict],
    *,
    vector_weight: float = 0.5,
    bm25_weight: float = 0.5,
    single_source_penalty: float = 0.1,
    min_final_score: Optional[float] = 0.05,
) -> Dict[int, Dict]:
    """双路融合：对两路命中做加权合并，并对单路命中打折。

    前提：两路 hits 必须已经做过归一化（含 normalized_score 字段）。
    本函数不做归一化也不做衰减，只做融合打分和最终阈值过滤。

    融合规则：
      - 双路命中：vector_norm*vw + bm25_norm*bw
      - 单路命中：norm * single_source_penalty（不乘 weight）

    阈值过滤：final_score < min_final_score 的 chunk 直接丢弃。

    Args:
        vector_hits: 向量检索结果（已含 normalized_score 字段）
        bm25_hits: BM25 检索结果（已含 normalized_score 字段）
        vector_weight: 向量路权重（双路命中时贡献系数）
        bm25_weight: BM25 路权重（双路命中时贡献系数）
        single_source_penalty: 单路命中折扣系数（最终再乘这个）
        min_final_score: 最低最终分门槛，低于此分直接丢弃；None 不过滤

    Returns:
        fused dict：{chunk_id: hit_dict_with_final_score_and_sources}
    """
    fused: Dict[int, Dict] = {}
    vec_ids = {h["id"] for h in vector_hits}
    bm_ids  = {h["id"] for h in bm25_hits}

    # 1. 先放 vector 一路
    for hit in vector_hits:
        cid = hit["id"]
        is_single = cid not in bm_ids
        norm = hit["normalized_score"]
        if is_single:
            final = norm * single_source_penalty
        else:
            final = norm * vector_weight
        fused[cid] = {
            **hit,
            "_final_score": final,
            "_vector_rank": None,
            "_bm25_rank": None,
            "_sources": ["vector"],
        }

    # 2. 再叠加 bm25 一路
    for hit in bm25_hits:
        cid = hit["id"]
        is_single = cid not in vec_ids
        norm = hit["normalized_score"]
        if cid in fused:
            fused[cid]["_final_score"] += norm * bm25_weight
            fused[cid]["_sources"].append("bm25")
        else:
            final = norm * single_source_penalty
            fused[cid] = {
                **hit,
                "_final_score": final,
                "_vector_rank": None,
                "_bm25_rank": None,
                "_sources": ["bm25"],
            }

    # 3. 最低阈值过滤
    if min_final_score is not None:
        fused = {cid: h for cid, h in fused.items() if h["_final_score"] >= min_final_score}

    return fused