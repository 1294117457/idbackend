-- ============================================================
-- 迁移：template 表增加 is_repeated 字段
-- 用途：控制模板是否允许学生重复提交申请
-- 语义：true = 允许重复提交（向后兼容已有模板）；false = 不允许重复提交
-- 日期：2026-07-18
-- ============================================================

ALTER TABLE template ADD COLUMN is_repeated BOOLEAN NOT NULL DEFAULT true;

COMMENT ON COLUMN template.is_repeated IS '是否允许重复提交：true=允许，false=不允许';

CREATE INDEX idx_template_is_repeated ON template(is_repeated);
