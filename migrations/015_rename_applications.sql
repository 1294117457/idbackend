-- 迁移 015：表重命名 + 修复 approved_count
-- 执行：psql $DATABASE_URL -f migrations/015_rename_applications.sql

BEGIN;

-- =============================================================================
-- Step 1: 删除 evaluation_applications 表（如存在）
-- =============================================================================
DROP TABLE IF EXISTS evaluation_applications CASCADE;
DROP SEQUENCE IF EXISTS evaluation_applications_id_seq;
-- 重建 sequences 因为 psql dump 可能有格式问题
DROP SEQUENCE IF EXISTS evaluation_applications_id_seq;

-- =============================================================================
-- Step 2: 更新外键约束 - 先删除旧的（指向 score_applications）
-- =============================================================================

-- 删除 application_operation 的旧外键
DO $$
DECLARE
    fk_name TEXT;
BEGIN
    SELECT conname INTO fk_name
    FROM pg_constraint
    WHERE conrelid = 'application_operation'::regclass
      AND contype = 'f'
      AND confrelid = 'score_applications'::regclass;
    
    IF fk_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE application_operation DROP CONSTRAINT %I', fk_name);
        RAISE NOTICE '删除旧外键: %', fk_name;
    END IF;
END $$;

-- 删除 application_proofs 的旧外键
DO $$
DECLARE
    fk_name TEXT;
BEGIN
    SELECT conname INTO fk_name
    FROM pg_constraint
    WHERE conrelid = 'application_proofs'::regclass
      AND contype = 'f'
      AND confrelid = 'score_applications'::regclass;
    
    IF fk_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE application_proofs DROP CONSTRAINT %I', fk_name);
        RAISE NOTICE '删除旧外键: %', fk_name;
    END IF;
END $$;

-- 删除 score_data 的旧外键
DO $$
DECLARE
    fk_name TEXT;
BEGIN
    SELECT conname INTO fk_name
    FROM pg_constraint
    WHERE conrelid = 'score_data'::regclass
      AND contype = 'f'
      AND confrelid = 'score_applications'::regclass;
    
    IF fk_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE score_data DROP CONSTRAINT %I', fk_name);
        RAISE NOTICE '删除旧外键: %', fk_name;
    END IF;
END $$;

-- =============================================================================
-- Step 3: 重命名 score_applications → applications
-- =============================================================================

-- 重命名主键约束
ALTER TABLE score_applications RENAME CONSTRAINT score_applications_pkey TO applications_pkey;

-- 重命名表
ALTER TABLE score_applications RENAME TO applications;

-- 重命名序列
ALTER SEQUENCE score_applications_id_seq RENAME TO applications_id_seq;

-- =============================================================================
-- Step 4: 添加 approved_count 字段
-- =============================================================================
ALTER TABLE applications ADD COLUMN IF NOT EXISTS approved_count INTEGER DEFAULT 0 NOT NULL;

-- =============================================================================
-- Step 5: 创建新的外键约束
-- =============================================================================

-- application_operation → applications
ALTER TABLE application_operation
    ADD CONSTRAINT application_operation_application_id_fkey
    FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE;

-- application_proofs → applications
ALTER TABLE application_proofs
    ADD CONSTRAINT application_proofs_application_id_fkey
    FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE;

-- score_data → applications
ALTER TABLE score_data
    ADD CONSTRAINT score_data_application_id_fkey
    FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE;

-- =============================================================================
-- Step 6: 重命名索引
-- =============================================================================
ALTER INDEX idx_application_user_template_status RENAME TO idx_applications_user_template_status;
ALTER INDEX idx_application_status RENAME TO idx_applications_status;
ALTER INDEX idx_application_category RENAME TO idx_applications_category;

-- =============================================================================
-- Step 7: 更新序列所有权
-- =============================================================================
ALTER SEQUENCE applications_id_seq OWNED BY applications.id;

COMMIT;

-- =============================================================================
-- 验证
-- =============================================================================
-- SELECT * FROM applications LIMIT 1;
-- SELECT approved_count FROM applications LIMIT 1;
-- \d applications
