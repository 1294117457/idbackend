-- ============================================================
-- 迁移：application_proofs 表增加 is_adjusted 字段
-- 用途：记录证明材料是否被老师修改过分数
-- 语义：false = 学生原始申报分；true = 老师修正过的分
-- 日期：2026-07-20
-- ============================================================

ALTER TABLE application_proofs ADD COLUMN is_adjusted BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN application_proofs.is_adjusted IS '是否被老师修正过：false=学生申报分，true=老师修正过的分';
