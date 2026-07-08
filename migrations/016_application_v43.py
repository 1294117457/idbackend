"""016_application_v43.py - Application 状态机升级 v4.3

变更点：
1. ApplicationStatus: 6态 → 5态
   - 移除 WITHDRAWN（学生APPLYING阶段撤回 → CANCELLED）
   - 移除 DISCARDED（学生草稿取消 → CANCELLED）
   - 新增 CANCELLED（学生主动取消，终态）
   - 新增 REVOKED（老师撤回通过的申请，终态）

2. ApplicationOperation: operation → status
   - operation 字段改为记录操作后的 application.status
   - 移除 ApplicationOperationType 枚举
   - 无 operator_type 字段（谁操作由业务逻辑隐含）

迁移策略：
- WITHDRAWN → CANCELLED
- DISCARDED → CANCELLED
- operation 值映射到对应的 status
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = '016_application_v43'
down_revision = '015_rename_applications'
branch_labels = ()
depends_on = None


def upgrade() -> None:
    # ==================== applications 表 ====================
    # 1. 更新 CHECK 约束（添加 CANCELLED/REVOKED，移除 WITHDRAWN/DISCARDED）
    op.execute("""
        ALTER TABLE applications
        DROP CONSTRAINT IF EXISTS applications_status_check,
        ADD CONSTRAINT applications_status_check
            CHECK (status IN ('DRAFT', 'APPLYING', 'PASSED', 'REJECTED', 'CANCELLED', 'REVOKED'))
    """)
    
    # 2. 数据迁移：WITHDRAWN/DISCARDED → CANCELLED
    op.execute("""
        UPDATE applications SET status = 'CANCELLED' 
        WHERE status IN ('WITHDRAWN', 'DISCARDED')
    """)

    # ==================== application_operation 表 ====================
    # 3. 添加临时列存储新的 status 值
    op.execute("""
        ALTER TABLE application_operation 
        ADD COLUMN new_status VARCHAR(20)
    """)
    
    # 4. 使用 CASE WHEN 将 operation 值映射为 status
    op.execute("""
        UPDATE application_operation SET new_status = 
            CASE operation
                WHEN 'CREATE_DRAFT' THEN 'DRAFT'
                WHEN 'UPDATE_DRAFT' THEN 'DRAFT'
                WHEN 'DISCARD_DRAFT' THEN 'CANCELLED'
                WHEN 'SUBMIT' THEN 'APPLYING'
                WHEN 'PASS' THEN 'PASSED'
                WHEN 'REJECT' THEN 'REJECTED'
                WHEN 'RESUBMIT' THEN 'APPLYING'
                WHEN 'WITHDRAW' THEN 'CANCELLED'
                WHEN 'REVOKE' THEN 'REVOKED'
                ELSE operation  -- 兜底
            END
    """)
    
    # 5. 删除旧列和 CHECK 约束
    op.execute("ALTER TABLE application_operation DROP CONSTRAINT IF EXISTS application_operation_operation_check")
    op.execute("ALTER TABLE application_operation DROP COLUMN IF EXISTS operation")
    
    # 6. 重命名临时列为 status
    op.execute("ALTER TABLE application_operation RENAME COLUMN new_status TO status")
    
    # 7. 添加 CHECK 约束
    op.execute("""
        ALTER TABLE application_operation 
        ADD CONSTRAINT application_operation_status_check
        CHECK (status IN ('DRAFT', 'APPLYING', 'PASSED', 'REJECTED', 'CANCELLED', 'REVOKED'))
    """)
    
    # 8. 重命名索引
    op.execute("ALTER INDEX IF EXISTS idx_operation_app_op RENAME TO idx_operation_app_status")


def downgrade() -> None:
    # 注意：降级时 operation 值无法准确恢复（CANELLED 可能来自 WITHDRAW 或 DISCARD_DRAFT）
    # CANCELLED 会被映射回 WITHDRAW
    
    # 1. 重命名索引
    op.execute("ALTER INDEX IF EXISTS idx_operation_app_status RENAME TO idx_operation_app_op")
    
    # 2. 恢复 applications 表 CHECK 约束
    op.execute("""
        ALTER TABLE applications
        DROP CONSTRAINT IF EXISTS applications_status_check,
        ADD CONSTRAINT applications_status_check
            CHECK (status IN ('DRAFT', 'APPLYING', 'PASSED', 'REJECTED', 'WITHDRAWN', 'DISCARDED'))
    """)
    
    # 3. 添加临时列存储旧的 operation 值
    op.execute("""
        ALTER TABLE application_operation 
        ADD COLUMN new_operation VARCHAR(30)
    """)
    
    # 4. 将 status 值映射回 operation
    op.execute("""
        UPDATE application_operation SET new_operation = 
            CASE status
                WHEN 'DRAFT' THEN 'CREATE_DRAFT'
                WHEN 'APPLYING' THEN 'SUBMIT'
                WHEN 'PASSED' THEN 'PASS'
                WHEN 'REJECTED' THEN 'REJECT'
                WHEN 'CANCELLED' THEN 'WITHDRAW'  -- CANCELLED 统一映射回 WITHDRAW
                WHEN 'REVOKED' THEN 'REVOKE'
                ELSE status
            END
    """)
    
    # 5. 删除 status 列和约束
    op.execute("ALTER TABLE application_operation DROP CONSTRAINT IF EXISTS application_operation_status_check")
    op.execute("ALTER TABLE application_operation DROP COLUMN IF EXISTS status")
    
    # 6. 重命名临时列
    op.execute("ALTER TABLE application_operation RENAME COLUMN new_operation TO operation")
    
    # 7. 添加旧 CHECK 约束
    op.execute("""
        ALTER TABLE application_operation 
        ADD CONSTRAINT application_operation_operation_check
        CHECK (operation IN ('CREATE_DRAFT', 'UPDATE_DRAFT', 'DISCARD_DRAFT', 'SUBMIT', 'PASS', 'REJECT', 'RESUBMIT', 'WITHDRAW', 'REVOKE'))
    """)
