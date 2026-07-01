"""模板、规则模型"""
from sqlalchemy import String, Integer, ForeignKey, Text, Boolean, DECIMAL, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List
import enum

from .base import Base, TimestampMixin


class TemplateType(str, enum.Enum):
    CONDITION = "CONDITION"  # 条件型
    TRANSFORM = "TRANSFORM"  # 转换型


class FieldType(str, enum.Enum):
    SCORE = "SCORE"
    DEMAND = "DEMAND"


class ScoreTemplate(Base, TimestampMixin):
    """加分模板表"""
    __tablename__ = "score_templates"

    template_name: Mapped[str] = mapped_column(String(100), nullable=False)
    template_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TemplateType.CONDITION.value
    )
    score_type: Mapped[int] = mapped_column(Integer, default=0)  # 0/1/2
    template_max_score: Mapped[float] = mapped_column(DECIMAL(5, 2), nullable=False)
    input_unit: Mapped[str] = mapped_column(String(50), default="")
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    review_count: Mapped[int] = mapped_column(Integer, default=1)

    field_id: Mapped[Optional[int]] = mapped_column(Integer)
    subcategory_id: Mapped[Optional[int]] = mapped_column(Integer)

    # 关系
    rules: Mapped[List["ScoreTemplateRule"]] = relationship(
        "ScoreTemplateRule", back_populates="template"
    )


class ScoreTemplateRule(Base, TimestampMixin):
    """模板计分规则表"""
    __tablename__ = "score_template_rules"

    template_id: Mapped[int] = mapped_column(
        ForeignKey("score_templates.id", ondelete="CASCADE")
    )
    rule_type: Mapped[str] = mapped_column(String(20))
    rule_name: Mapped[Optional[str]] = mapped_column(String(100))
    rule_score: Mapped[Optional[float]] = mapped_column(DECIMAL(5, 2))
    priority: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[Optional[str]] = mapped_column(Text)

    # 关系
    template: Mapped["ScoreTemplate"] = relationship(
        "ScoreTemplate", back_populates="rules"
    )
    attributes: Mapped[List["RuleAttribute"]] = relationship(
        "RuleAttribute", secondary="rule_attribute_mapping"
    )


class RuleAttribute(Base, TimestampMixin):
    """规则属性表"""
    __tablename__ = "rule_attributes"

    attribute_code: Mapped[str] = mapped_column(String(50), nullable=False)
    attribute_type: Mapped[str] = mapped_column(String(20), nullable=False)
    attribute_value: Mapped[Optional[str]] = mapped_column(Text)  # 条件值或公式
    input_max: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    input_min: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    input_interval: Mapped[Optional[str]] = mapped_column(String(20))  # OPEN/CLOSED
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class RuleAttributeMapping(Base, TimestampMixin):
    """规则属性关联表"""
    __tablename__ = "rule_attribute_mapping"

    rule_id: Mapped[int] = mapped_column(
        ForeignKey("score_template_rules.id", ondelete="CASCADE")
    )
    attribute_id: Mapped[int] = mapped_column(
        ForeignKey("rule_attributes.id", ondelete="CASCADE")
    )
    is_required: Mapped[bool] = mapped_column(Boolean, default=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)


class DemandTemplate(Base, TimestampMixin):
    """需求模板表"""
    __tablename__ = "demand_templates"

    template_name: Mapped[str] = mapped_column(String(100), nullable=False)
    conditions: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class FieldConfig(Base, TimestampMixin):
    """字段配置表"""
    __tablename__ = "field_config"

    field_key: Mapped[str] = mapped_column(String(50), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    field_type: Mapped[str] = mapped_column(String(20), nullable=False)
    max_score: Mapped[Optional[float]] = mapped_column(DECIMAL(5, 2))
    conditions: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    description: Mapped[Optional[str]] = mapped_column(String(255))
    college_code: Mapped[Optional[str]] = mapped_column(String(50))
    academic_year: Mapped[Optional[int]] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String(50), default="system")

    # 关系
    subcategories: Mapped[List["FieldSubcategory"]] = relationship(
        "FieldSubcategory", back_populates="field_config", cascade="all, delete-orphan"
    )


class FieldSubcategory(Base, TimestampMixin):
    """字段细分表"""
    __tablename__ = "field_subcategory"

    field_id: Mapped[int] = mapped_column(
        ForeignKey("field_config.id", ondelete="CASCADE")
    )
    sub_key: Mapped[str] = mapped_column(String(50), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    max_score: Mapped[float] = mapped_column(DECIMAL(5, 2), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # 关系
    field_config: Mapped["FieldConfig"] = relationship(
        "FieldConfig", back_populates="subcategories"
    )
