-- 添加 reviewer_ids JSONB 字段（幂等）
-- PostgreSQL

-- 列不存在时才添加
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'applications' AND column_name = 'reviewer_ids'
    ) THEN
        ALTER TABLE applications
        ADD COLUMN reviewer_ids JSONB DEFAULT '[]'::JSONB NOT NULL;

        -- GIN 索引支持 JSONB 包含查询（contains）
        CREATE INDEX idx_applications_reviewer_ids ON applications USING GIN (reviewer_ids);

        RAISE NOTICE 'reviewer_ids 列 + GIN 索引创建成功';
    ELSE
        RAISE NOTICE 'reviewer_ids 列已存在，跳过';
    END IF;
END
$$;
