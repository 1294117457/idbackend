"""017_add_extra_info_field.py - 新增 extra_info_field 表

变更点：
1. 新建 extra_info_field 表，用于老师配置学生扩展字段（如四六级成绩、游泳水平）
2. users.extra_info 已有 JSONB 字段，无需迁移

表结构：
- id / name / type / options / is_active / sort_order / description / created_at / updated_at

存储结构（users.extra_info jsonb）：
- key: f_{id} 格式，如 f_1, f_2
- value: 根据 type 不同为 string / number / array
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = '017_add_extra_info_field'
down_revision = '016_application_v43'
branch_labels = ()
depends_on = None


def upgrade() -> None:
    # 创建 extra_info_field 表
    op.execute("""
        CREATE TABLE IF NOT EXISTS extra_info_field (
            id          SERIAL PRIMARY KEY,
            name        VARCHAR(128) NOT NULL,
            type        VARCHAR(20) NOT NULL DEFAULT 'TEXT',
            options     JSONB NOT NULL DEFAULT '[]',
            is_active   BOOLEAN NOT NULL DEFAULT TRUE,
            sort_order  INTEGER NOT NULL DEFAULT 0,
            description VARCHAR(255),
            created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)

    # 创建索引
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_extra_info_field_sort
            ON extra_info_field (sort_order, id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_extra_info_field_active
            ON extra_info_field (is_active)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS extra_info_field")
