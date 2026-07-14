-- 为 reviewer_ids JSONB 字段添加 GIN 索引
-- 支持: SELECT ... FROM applications WHERE reviewer_ids::jsonb @> to_jsonb(?)::jsonb

BEGIN;

CREATE INDEX IF NOT EXISTS idx_applications_reviewer_ids_gin
ON applications USING gin (reviewer_ids jsonb_path_ops);

COMMIT;
