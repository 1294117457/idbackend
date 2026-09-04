"""申请域模型（v5 充血模型 + Domain Events）

三个实体:
  - Application          申请主表（核心）
  - ApplicationProof     申请证明（辅助表）
  - ApplicationOperation 操作日志（事件审计）

v5 充血模型职责：
  - Application 承载所有状态机逻辑（cancel/submit/approve/reject/revoke）
  - ApplicationProof 承载证明材料的审核行为（approve/reject/reset）
  - Domain Event 由领域方法返回，由 Service 层处理（持久化、发通知等）
  - schemas/ 只做 DTO 转换，不含任何业务逻辑
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional, List

from sqlalchemy import (
    String, Integer, ForeignKey, DECIMAL, Numeric, Text, Enum as SAEnum, Index,
    Boolean, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin
from src.exceptions import ConflictError

# ════════════════════════════════════════════════════════════════════════
# 状态枚举
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
# Domain Events（领域事件）
# ════════════════════════════════════════════════════════════════════════
@dataclass
class ApplicationEvent:
    """Application 领域事件的基类"""

    application_id: int
    operator_id: int
    operator_name: str
    operation: str
    remark: Optional[str] = None
    occurred_at: datetime = field(default_factory=datetime.utcnow)


# 学生端事件
@dataclass
class ApplicationSubmitted(ApplicationEvent):
    """学生提交申请（首次提交或重新提交）"""
    pass


@dataclass
class ApplicationCancelled(ApplicationEvent):
    """学生取消申请"""
    pass


@dataclass
class ApplicationRevoked(ApplicationEvent):
    """学生撤回已通过的申请"""
    pass


# 审核员端事件
@dataclass
class ApplicationApproved(ApplicationEvent):
    """审核员投票通过"""
    is_final: bool = False


@dataclass
class ApplicationRejected(ApplicationEvent):
    """审核员投票驳回"""
    pass


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
    # 历史引用字段：application 主体不需要与 template 表存在外键关系
    # - 删除 template 时 application 不应被任何方式改动（UPDATE / CASCADE）
    # - 真正的展示数据由 template_name / category_id / apply_score 快照字段承担
    template_id: Mapped[int] = mapped_column(Integer, index=True)
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
        JSONB, nullable=True, default=list,
    )

    # ★ v7 字段重命名 + 结构简化
    # 提交时把学生在表单上选择的 attribute 按 rule 分组，
    # 存为 {rule.name: attribute.name} 的扁平结构
    # - 一条 application 的每个 rule 只对应一个 attribute.name（CONDITION 单选语义）
    # - TRANSFORM 类型不存 rule_info（apply_score / gain_score 已承载分数）
    # - 提交后与 rule/attribute 表完全无关（rule 改名/删除不影响 application 快照）
    rule_info: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    # ★ v10：学生备注（学生提交申请时录入的说明性文本）
    # - 选填，≤500 字符（与前端 maxlength 对齐）
    # - 写入时机：save / submit / edit（apply_to_model 处理 None 时不动 DB）
    # - 不进 application_operation 审计日志
    # - 仅申请本身快照属性，与审核员备注（ApplicationPayload.remark → ApplicationOperation.remark）完全独立
    student_remark: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        default=None,
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
        Index("idx_application_status", "status"),
        Index("idx_application_category", "category_id"),
        Index(
            "idx_reviewers",
            "reviewer_ids",
            postgresql_using="gin",
            postgresql_ops={"reviewer_ids": "jsonb_path_ops"},
        ),
    )

    # ════════════════════════════════════════════════════════════════════
    # 状态机（学生端）
    # ════════════════════════════════════════════════════════════════════

    def can_be_cancelled_by(self, user_id: int) -> bool:
        """学生是否有权取消此申请"""
        return (
            self.user_id == user_id
            and self.status
            in {ApplicationStatus.DRAFT.value, ApplicationStatus.APPLYING.value}
        )

    def can_be_edited(self) -> bool:
        """申请是否处于可编辑状态（DRAFT）"""
        return self.status == ApplicationStatus.DRAFT.value

    def cancel(self, operator_id: int, operator_name: str, remark: Optional[str] = None) -> ApplicationCancelled:
        """取消申请（仅 DRAFT / APPLYING），返回领域事件"""
        if self.status not in {
            ApplicationStatus.DRAFT.value,
            ApplicationStatus.APPLYING.value,
        }:
            raise ConflictError(f"仅 DRAFT 或 APPLYING 可取消，当前：{self.status}")
        self.status = ApplicationStatus.CANCELLED.value
        return ApplicationCancelled(
            application_id=self.id,
            operator_id=operator_id,
            operator_name=operator_name,
            operation=ApplicationStatus.CANCELLED.value,
            remark=remark,
        )

    def submit(self, operator_id: int, operator_name: str) -> ApplicationSubmitted:
        """重新提交进入审核流（从 DRAFT / REJECTED / REVOKED），返回领域事件"""
        if self.status not in {
            ApplicationStatus.DRAFT.value,
            ApplicationStatus.REJECTED.value,
            ApplicationStatus.REVOKED.value,
        }:
            raise ConflictError(f"仅 DRAFT / REJECTED / REVOKED 可提交，当前：{self.status}")
        self.status = ApplicationStatus.APPLYING.value
        self.approved_count = 0
        self.rejected_count = 0
        self.reviewer_ids = []
        return ApplicationSubmitted(
            application_id=self.id,
            operator_id=operator_id,
            operator_name=operator_name,
            operation=ApplicationStatus.APPLYING.value,
        )

    def revoke(self, operator_id: int, operator_name: str, remark: str) -> ApplicationRevoked:
        """撤回已通过的申请，返回领域事件"""
        if self.status != ApplicationStatus.PASSED.value:
            raise ConflictError(f"仅 PASSED 可撤回，当前：{self.status}")
        self.status = ApplicationStatus.REVOKED.value
        self.gain_score = Decimal("0")
        return ApplicationRevoked(
            application_id=self.id,
            operator_id=operator_id,
            operator_name=operator_name,
            operation=ApplicationStatus.REVOKED.value,
            remark=remark,
        )

    def recalculate_gain_score(self) -> None:
        """重新计算实际得分（PASSED 时按已通过 proof 求和）"""
        if self.status != ApplicationStatus.PASSED.value:
            return
        self.gain_score = sum(
            (p.proof_score for p in self.proofs if p.status == ProofStatus.APPROVED.value),
            Decimal("0"),
        )

    # ════════════════════════════════════════════════════════════════════
    # 状态机（审核员端）
    # ════════════════════════════════════════════════════════════════════

    def has_voted(self, reviewer_id: int) -> bool:
        """审核员是否已投过票"""
        return reviewer_id in (self.reviewer_ids or [])

    def approve(self, reviewer_id: int, operator_id: int, operator_name: str) -> ApplicationApproved:
        """审核员投通过票，返回领域事件

        Returns:
            ApplicationApproved.is_final = True  → 申请已达到终态（approved_count >= review_count）
            ApplicationApproved.is_final = False → 仍在审核中
        """
        if self.status != ApplicationStatus.APPLYING.value:
            raise ConflictError(f"仅 APPLYING 可审核，当前：{self.status}")
        if self.has_voted(reviewer_id):
            raise ConflictError("该审核员已投过票")

        self.reviewer_ids = (self.reviewer_ids or []) + [reviewer_id]
        self.approved_count += 1

        is_final = False
        if self.approved_count >= self.review_count:
            self.status = ApplicationStatus.PASSED.value
            self.recalculate_gain_score()
            is_final = True

        return ApplicationApproved(
            application_id=self.id,
            operator_id=operator_id,
            operator_name=operator_name,
            operation=self.status,
            is_final=is_final,
        )

    def reject(self, reviewer_id: int, operator_id: int, operator_name: str, remark: str) -> ApplicationRejected:
        """审核员投驳回票，返回领域事件"""
        if self.status != ApplicationStatus.APPLYING.value:
            raise ConflictError(f"仅 APPLYING 可审核，当前：{self.status}")
        if self.has_voted(reviewer_id):
            raise ConflictError("该审核员已投过票")

        self.reviewer_ids = (self.reviewer_ids or []) + [reviewer_id]
        self.status = ApplicationStatus.REJECTED.value
        self.rejected_count += 1

        return ApplicationRejected(
            application_id=self.id,
            operator_id=operator_id,
            operator_name=operator_name,
            operation=self.status,
            remark=remark,
        )


# ════════════════════════════════════════════════════════════════════════
# ApplicationProof（辅助表）
# ════════════════════════════════════════════════════════════════════════
class ApplicationProof(Base, TimestampMixin):
    """申请证明材料（辅助展示表）"""

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
    is_adjusted: Mapped[bool] = mapped_column(Boolean, default=False)

    application: Mapped["Application"] = relationship(back_populates="proofs")
    file: Mapped[Optional["FileMetadata"]] = relationship("FileMetadata", lazy="joined")

    __table_args__ = (
        Index("idx_proofs_application", "application_id"),
        Index("idx_proofs_application_status", "application_id", "status"),
    )

    def approve(self) -> None:
        """标记为已通过"""
        self.status = ProofStatus.APPROVED.value

    def reject(self) -> None:
        """标记为已驳回"""
        self.status = ProofStatus.REJECTED.value

    def reset_to_pending(self) -> None:
        """换文件后重置为待审核"""
        self.status = ProofStatus.PENDING.value


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