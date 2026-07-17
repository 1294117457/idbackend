-- 为查询条件字段添加索引
-- 应用场景:
--   1. (user_id, status)       → list_applications_by_user 按学生+状态筛选
--   2. (operator_id)          → list_my_audit_history 按审核员查操作历史

BEGIN;

-- 索引1: applications 表 (user_id, status) 复合索引
-- 支持: SELECT ... FROM applications WHERE user_id = ? AND status = ?
CREATE INDEX IF NOT EXISTS idx_application_user_status
ON applications (user_id, status);

-- 索引2: application_operation 表 operator_id 单列索引
-- 支持: SELECT ... FROM application_operation WHERE operator_id = ?
CREATE INDEX IF NOT EXISTS idx_operation_operator
ON application_operation (operator_id);

COMMIT;
