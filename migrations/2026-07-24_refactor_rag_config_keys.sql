-- ============================================================
-- 迁移：system_config 表 RAG 字段重构
-- 用途：把过时的 RRF / source_discount / bm25_rank1_weight / hybrid_weight /
--      search_mode 替换为新的"召回参数 + 融合权重"两段式字段
-- 日期：2026-07-24
--
-- 新增字段（与 src.infra.config.Settings、src.app.schemas.system_config.RagConfigKeys 对齐）
--   召回参数：RAG_TOP_K / RAG_CANDIDATE_K / RAG_MIN_SCORE
--   融合权重：RAG_VECTOR_WEIGHT / RAG_BM25_WEIGHT / RAG_SINGLE_SOURCE_PENALTY / RAG_SAME_DOC_DECAY
--
-- 物理模型不变（仍是 system_config KV 表），仅清理/插入配置项
-- ============================================================

-- 1. 删除被废弃的字段（幂等）
DELETE FROM system_config WHERE config_key IN (
    'RAG_SEARCH_MODE',
    'RAG_RRF_K',
    'RAG_SOURCE_DISCOUNT',
    'RAG_BM25_RANK1_WEIGHT',
    'RAG_HYBRID_WEIGHT'
);

-- 2. 插入新字段（已存在则跳过，保留 DB 里已有人调过的值）
INSERT INTO system_config (config_key, config_value, category, value_type, description, is_sensitive)
VALUES
    -- 召回参数
    ('RAG_TOP_K',         '5',   'RAG', 'int',   'RAG 检索：最终返回条数',                 false),
    ('RAG_CANDIDATE_K',   '0',   'RAG', 'int',   'RAG 检索：候选池大小（0=自动）',        false),
    ('RAG_MIN_SCORE',     '0.05','RAG', 'float', 'RAG 检索：融合后最低分门槛',             false),
    -- 融合权重
    ('RAG_VECTOR_WEIGHT',          '1.0', 'RAG', 'float', 'RAG 检索：向量路权重',           false),
    ('RAG_BM25_WEIGHT',            '1.0', 'RAG', 'float', 'RAG 检索：BM25 路权重',           false),
    ('RAG_SINGLE_SOURCE_PENALTY',  '0.5', 'RAG', 'float', 'RAG 检索：单路命中折扣',         false),
    ('RAG_SAME_DOC_DECAY',         '0.7', 'RAG', 'float', 'RAG 检索：同文档第 n 衰减系数',  false)
ON CONFLICT (config_key) DO NOTHING;
