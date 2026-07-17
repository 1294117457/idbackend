-- 解耦 application 与 template 的外键约束
-- 设计动机：
--   application 主体已经把 template_name / category_id / apply_score
--   同步为快照字段，业务路径（list / score 计算 / 审核）完全不 JOIN template。
--   template 删除时不应影响 application 表（既不能 CASCADE 删，
--   也不能 SET NULL 把 template_id 改写成 NULL）。
--
-- 实施内容：
--   1. 移除 applications.template_id 的外键约束
--   2. 删除已无人查询使用的 (user_id, template_id, status) 三列组合索引
--      注：(user_id, status) 二列索引已在 migrate_add_query_indexes.sql 里建过

BEGIN;

-- 1. 移除 FK 约束（IF EXISTS 兜底，幂等）
ALTER TABLE applications
    DROP CONSTRAINT IF EXISTS applications_template_id_fkey;

-- 2. 删除冗余的三列组合索引
DROP INDEX IF EXISTS idx_application_user_template_status;

COMMIT;
