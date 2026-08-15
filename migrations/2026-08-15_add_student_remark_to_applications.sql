-- ============================================================
-- 迁移：applications 表增加 student_remark 字段
-- 用途：学生在提交申请时录入的一段说明性文本（选填，≤500 字符）
-- 语义：随申请快照保存，审核员可在审核弹窗中查看
-- 日期：2026-08-15
-- ============================================================

ALTER TABLE applications
  ADD COLUMN IF NOT EXISTS student_remark VARCHAR(500);

COMMENT ON COLUMN applications.student_remark IS
  '学生备注（v1）：学生在提交申请时录入的说明性文本，选填，≤500 字符。'
  '申请快照属性，与 rule_info 平级，不进入 operation_log。';
