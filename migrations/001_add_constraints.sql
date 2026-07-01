-- idpython 数据库迁移脚本
-- 执行前请备份数据库

-- ============================================
-- 1. 添加 field_config 唯一约束
-- ============================================
-- 注意：如果唯一约束已存在，跳过此步骤
-- ALTER TABLE field_config
-- ADD CONSTRAINT uk_key_college_year 
-- UNIQUE (field_key, college_code, academic_year);

-- ============================================
-- 2. 添加 rule_attributes 唯一约束
-- ============================================
-- 注意：MySQL 部分唯一约束需要指定前缀长度
-- ALTER TABLE rule_attributes
-- ADD CONSTRAINT uk_code_value_type 
-- UNIQUE (attribute_code, attribute_value(100), attribute_type);

-- ============================================
-- 3. 创建 demand_applications 表
-- ============================================
CREATE TABLE IF NOT EXISTS demand_applications (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id VARCHAR(255) NOT NULL,
    application_data JSON NOT NULL,
    submit_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_student_id (student_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ============================================
-- 4. score_applications 表添加 revoke_reason 字段
-- ============================================
-- ALTER TABLE score_applications
-- ADD COLUMN revoke_reason VARCHAR(255) AFTER gain_score;

-- ============================================
-- 5. 添加 rule_attribute_mapping 唯一约束
-- ============================================
-- ALTER TABLE rule_attribute_mapping
-- ADD CONSTRAINT uk_rule_attribute 
-- UNIQUE (rule_id, attribute_id);

-- ============================================
-- 验证表结构
-- ============================================
SHOW TABLES LIKE '%demand_applications%';
SHOW TABLES LIKE '%rule_attributes%';
SHOW TABLES LIKE '%field_config%';
