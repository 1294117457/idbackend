"""申请域模型（v4.3）

三个实体:
  - Application          申请主表（核心）
  - ApplicationProof     申请证明（辅助表）
  - ApplicationOperation 操作日志（事件审计）
"""
from __future__ import annotations

import enum
from decimal import Decimal
from typing import Optional, List

from sqlalchemy import (
    String, Integer, ForeignKey, DECIMAL, Numeric, Text, Enum as SAEnum, Index,
    JSON,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

# ════════════════════════════════════════════════════════════════════════
# 状态枚举（v4.3 字符串 5 态）
# ════════════════════════════════════════════════════════════════════════
class ApplicationStatus(str, enum.Enum):
    """application 状态机（v4.3 字符串 5 态）"""
    DRAFT = "DRAFT"          # 草稿（学生可编辑）
    APPLYING = "APPLYING"    # 审核中（学生锁定）
    PASSED = "PASSED"       # 通过（终态）
    REJECTED = "REJECTED"   # 拒绝（可重提，老师操作）
    CANCELLED = "CANCELLED" # 已取消（终态，学生主动取消）
    REVOKED = "REVOKED"     # 已撤回（终态，老师撤回通过的申请）


class ProofStatus(str, enum.Enum):
    """proof 状态机（v4.3 字符串 3 态）"""
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# ════════════════════════════════════════════════════════════════════════
# Application（核心实体）
# ════════════════════════════════════════════════════════════════════════
class Application(Base, TimestampMixin):
    """加分申请表（核心实体）"""
    __tablename__ = "applications"

    # 基础
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    template_id: Mapped[int] = mapped_column(ForeignKey("template.id"))
    template_name: Mapped[str] = mapped_column(String(100))   # 快照，防改名
    category_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("template_category.id"), nullable=True,    # 迁移期允许 NULL
    )

    # 分数快照
    apply_score: Mapped[Decimal] = mapped_column(
        DECIMAL(5, 2), default=0,
    )                                                       # 计算引擎决定，save_draft 时固化
    gain_score: Mapped[Decimal] = mapped_column(
        DECIMAL(5, 2), default=0,
    )                                                       # PASSED 时一次性写为 apply_score

    # 状态（v4.3 字符串 5 态）
    status: Mapped[str] = mapped_column(
        String(20),
        SAEnum(ApplicationStatus, native_enum=False, length=20, validate_strings=True),
        default=ApplicationStatus.DRAFT.value,
    )

    # 审核员投票累计（不同审核员累计语义）
    review_count: Mapped[int] = mapped_column(Integer, default=1)
    approved_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)

    # 审核员名单（v4.3：只要审过 proof 或投过 PASS/REJECT，即进入此列表）
    # 用于"我是否审核过"的业务判断，辅助列表互斥分流
    reviewer_ids: Mapped[Optional[list[int]]] = mapped_column(
        JSON, nullable=True, default=list,
    )

    # 关系
    user: Mapped["User"] = relationship(back_populates="applications")
    proofs: Mapped[List["ApplicationProof"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )
    operations: Mapped[List["ApplicationOperation"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ApplicationOperation.created_at",
        lazy="selectin",
    )

    __table_args__ = (
        Index("idx_application_user_template_status", "user_id", "template_id", "status"),
        Index("idx_application_status", "status"),
        Index("idx_application_category", "category_id"),
        Index(
            "idx_reviewers",
            "reviewer_ids",
            postgresql_using="gin",
            postgresql_ops={"reviewer_ids": "jsonb_path_ops"},
        ),
    )


# ════════════════════════════════════════════════════════════════════════
# ApplicationProof（辅助表）
# ════════════════════════════════════════════════════════════════════════
class ApplicationProof(Base, TimestampMixin):
    """申请证明材料（辅助展示表）

    v4.2 关键决策：
      - proof.status 是会签中间状态，任意审核员都可修改（覆盖前审核员的决定）
      - proof 不需要 review_count / approved_count 字段
      - file_id nullable，允许纯文字描述
    """
    __tablename__ = "application_proofs"

    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"),
    )
    file_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("file_metadata.id"), nullable=True,
    )
    proof_score: Mapped[Decimal] = mapped_column(DECIMAL(5, 2))
    status: Mapped[str] = mapped_column(
        String(20),
        SAEnum(ProofStatus, native_enum=False, length=20, validate_strings=True),
        default=ProofStatus.PENDING.value,
    )

    # 关系
    # file 用 lazy="joined"：保证从 application 加载 proofs 后 file 也一次 JOIN 进来，
    # 避免在 async 路由层访问 proof.file 触发 lazy load（MissingGreenlet）。
    # 现有的 selectinload(Application.proofs) 会与 joined 兼容，不重复发 SQL。
    application: Mapped["Application"] = relationship(back_populates="proofs")
    file: Mapped[Optional["FileMetadata"]] = relationship(
        "FileMetadata", lazy="joined",
    )

    __table_args__ = (
        Index("idx_proofs_application", "application_id"),
        Index("idx_proofs_application_status", "application_id", "status"),
    )


# ════════════════════════════════════════════════════════════════════════
# ApplicationOperation（事件审计）
# ════════════════════════════════════════════════════════════════════════
class ApplicationOperation(Base, TimestampMixin):
    """申请操作审计日志（application 层）

    v4.3 关键决策：
      - operation 字段存储操作后的 application.status（DRAFT/APPLYING/PASSED/REJECTED/CANCELLED/REVOKED）
      - 没有 operator_type 字段（谁操作由业务逻辑隐含）
      - 没有 target_id / target_type 字段
      - 草稿修改（save_draft）本期不写——噪音大
    """
    __tablename__ = "application_operation"

    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"),
    )
    operator_id: Mapped[int] = mapped_column(Integer)
    operator_name: Mapped[str] = mapped_column(String(100))
    # 操作后 application 的状态（DRAFT / APPLYING / PASSED / REJECTED / CANCELLED / REVOKED）
    operation: Mapped[str] = mapped_column(
        String(20),
        SAEnum(ApplicationStatus, native_enum=False, length=20, validate_strings=True),
    )
    remark: Mapped[Optional[str]] = mapped_column(Text)

    application: Mapped["Application"] = relationship(back_populates="operations")

    __table_args__ = (
        Index("idx_operation_application", "application_id"),
        Index("idx_operation_app_status", "application_id", "operation"),
    )