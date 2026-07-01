"""加分申请模型"""
from sqlalchemy import String, Integer, ForeignKey, JSON, Text, Enum, DECIMAL
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List
import enum

from .base import Base, TimestampMixin


class ApplicationStatus(int, enum.Enum):
    PENDING = 0  # 待审核
    APPROVED = 1  # 通过
    REJECTED = 2  # 驳回


class ScoreType(int, enum.Enum):
    ACADEMIC = 0  # 学业类
    SPECIALTY = 1  # 专长类
    ALL = 2  # 全部


class Application(Base, TimestampMixin):
    """加分申请表"""
    __tablename__ = "score_applications"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    student_id: Mapped[str] = mapped_column(String(50))
    student_name: Mapped[Optional[str]] = mapped_column(String(100))
    major: Mapped[Optional[str]] = mapped_column(String(100))
    enrollment_year: Mapped[Optional[int]] = mapped_column(Integer)

    template_name: Mapped[str] = mapped_column(String(100))
    score_type: Mapped[int] = mapped_column(Integer, default=0)

    apply_score: Mapped[float] = mapped_column()  # 申请分数
    gain_score: Mapped[Optional[float]] = mapped_column()  # 最终得分

    status: Mapped[int] = mapped_column(Integer, default=0)

    # 审核相关
    review_count: Mapped[int] = mapped_column(Integer, default=1)
    current_review_count: Mapped[int] = mapped_column(Integer, default=0)
    reviewer_ids: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    review_records: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    remark: Mapped[Optional[str]] = mapped_column(Text)

    # 用户输入
    apply_input: Mapped[Optional[float]] = mapped_column()
    proofs_input: Mapped[float] = mapped_column(default=0.0)

    # 关联
    rule_id: Mapped[Optional[int]] = mapped_column(ForeignKey("score_template_rules.id"))
    template_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("score_templates.id")
    )

    # 关系
    user: Mapped["User"] = relationship("User", back_populates="applications")
    proofs: Mapped[List["ApplicationProof"]] = relationship(
        "ApplicationProof", back_populates="application"
    )


class ApplicationProof(Base, TimestampMixin):
    """申请证明材料表"""
    __tablename__ = "application_proofs"

    application_id: Mapped[int] = mapped_column(
        ForeignKey("score_applications.id", ondelete="CASCADE")
    )
    proof_file_id: Mapped[int] = mapped_column(ForeignKey("file_metadata.id"))
    proof_value: Mapped[float] = mapped_column()  # 证明材料加分值

    review_count: Mapped[int] = mapped_column(Integer, default=1)
    approved_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[int] = mapped_column(Integer, default=0)

    reviewer_ids: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    review_records: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    remark: Mapped[Optional[str]] = mapped_column(String(500))

    # 关系
    application: Mapped["Application"] = relationship(
        "Application", back_populates="proofs"
    )
    file: Mapped["FileMetadata"] = relationship("FileMetadata")


class EvaluationApplication(Base, TimestampMixin):
    """综测申请表 (需求类)"""
    __tablename__ = "evaluation_applications"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    student_id: Mapped[str] = mapped_column(String(20))
    student_name: Mapped[str] = mapped_column(String(100))

    foreign_language_level: Mapped[Optional[str]] = mapped_column(String(200))
    disciplinary_violations: Mapped[int] = mapped_column(Integer, default=0)
    failed_courses: Mapped[int] = mapped_column(Integer, default=0)
    special_skills_remark: Mapped[Optional[str]] = mapped_column(Text)

    attachment_files: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    application_reason: Mapped[Optional[str]] = mapped_column(Text)

    status: Mapped[str] = mapped_column(String(20), default="pending")
    required_approvals: Mapped[int] = mapped_column(Integer, default=1)
    current_approvals: Mapped[int] = mapped_column(Integer, default=0)
    approval_records: Mapped[Optional[list]] = mapped_column(JSON, default=list)
