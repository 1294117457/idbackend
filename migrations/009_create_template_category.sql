-- idpython 数据库迁移脚本 (009)
-- 模板分类树表 template_category
-- Layer 1：分类层级 + 各级分值上限 + is_leaf 状态机字段
--
-- 详见 docs/core-function/四层职责设计.md 与 docs/core-function/template_category.md

-- ============================================
-- 1. 创建 template_category 表
-- ============================================
CREATE TABLE IF NOT EXISTS template_category (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    parent_id   INTEGER REFERENCES template_category(id) ON DELETE CASCADE,
    max_score   DECIMAL(5,2) NOT NULL CHECK (max_score >= 0),
    is_leaf     BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    description VARCHAR(255),
    created_at  TIMESTAMP,
    updated_at  TIMESTAMP,
    CONSTRAINT ck_template_category_max_score_nonneg CHECK (max_score >= 0)
);

-- ============================================
-- 2. 索引
-- ============================================
CREATE INDEX IF NOT EXISTS idx_template_category_parent_sort
    ON template_category (parent_id, sort_order, id);

CREATE INDEX IF NOT EXISTS idx_template_category_active
    ON template_category (is_active);

-- ============================================
-- 3. 验证
-- ============================================
\d template_category