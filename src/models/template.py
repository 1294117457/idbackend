"""Template / Rule / Attribute 模型（v4 设计）

Layer 2 模型设计哲学（docs/core-function/template.md / 四层职责设计.md）：
- Template：聚合根（计分模板的入口），绑定 Rule
- Rule：计分单位，绑定 Attribute；带 type 字段（CONDITION / TRANSFORM）
- Attribute：选项 / 公式，带 type 字段（与 Rule.type 联动）
- TemplateRule / RuleAttribute：极简多对多关联表

type 字段只放 Rule + Attribute 两层（template 不加 type），
业务允许 template 混用 CONDITION + TRANSFORM rule。
"""
from sqlalchemy import (
    String,
    Integer,
    ForeignKey,
    Text,
    Boolean,
    DECIMAL,
    CheckConstraint,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List
import enum

from .base import Base, TimestampMixin


class AttributeType(str, enum.Enum):
    """属性 / 规则类型枚举（统一 Rule.type 和 Attribute.type 复用）"""

    CONDITION = "CONDITION"  # 条件型：选 attribute → 加 rule.score
    TRANSFORM = "TRANSFORM"  # 转换型：用户输入数值 → 按 attribute.value 公式计算


# ============================================================
# Template（聚合根）
# ============================================================

class Template(Base, TimestampMixin):
    """模板（聚合根）—— v4 设计：不含 type 字段

    字段：
    - name: 模板名
    - category_id: 绑定的 template_category.id（叶子节点）
    - max_score: 本模板单次申请上限
    - review_count: 审核员人数
    - sort_order: 模板在所属分类下的展示顺序
    - description: 备注
    - is_active: 软启用
    """
    __tablename__ = "template"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("template_category.id", ondelete="CASCADE"),
        nullable=False,
    )
    max_score: Mapped[float] = mapped_column(DECIMAL(5, 2), nullable=False)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # 关系
    category: Mapped["TemplateCategory"] = relationship(  # noqa: F821
        "TemplateCategory",
        back_populates="templates",
        foreign_keys="[Template.category_id]",
    )
    # v4: Template → Rule 是多对多（template_rule 极简关联表）；
    # 直接通过 secondary=template_rule，让 ORM 表示为 Rule 列表，
    # 这样 selectinload(Template.rules).selectinload(Rule.attributes) 可贯通。
    # 注意：写操作（bind / unbind）仍由 TemplateRepository 显式管理 TemplateRule 行，
    # Template.rules 仅作为查询视图（与文档 template.md 第 264 行 ASCII 图一致）。
    rules: Mapped[List["Rule"]] = relationship(
        "Rule",
        secondary="template_rule",
        back_populates="templates",
        passive_deletes=True,
        viewonly=True,
    )

    __table_args__ = (
        CheckConstraint("max_score >= 0", name="ck_template_max_score_nonneg"),
        Index("idx_template_category", "category_id"),
        Index("idx_template_active", "is_active"),
    )


# ============================================================
# Rule（计分单位，v4 新增 type 字段）
# ============================================================

class Rule(Base, TimestampMixin):
    """规则（计分单位）—— v4 设计：新增 type 字段

    字段：
    - type: CONDITION / TRANSFORM（与 attribute.type 联动）
    - score: CONDITION 时必填，TRANSFORM 时必须 NULL（由 service 层校验）
    - name: 规则名
    - sort_order: rule 的全局显示顺序（同一 rule 跨 template 顺序一致）
    - description: 备注
    - is_active: 软启用
    """
    __tablename__ = "rule"

    type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=AttributeType.CONDITION.value,
    )
    score: Mapped[Optional[float]] = mapped_column(DECIMAL(5, 2))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # 关系
    attributes: Mapped[List["Attribute"]] = relationship(
        "Attribute",
        secondary="rule_attribute",
        back_populates="rules",
        passive_deletes=True,
    )
    # v4: 改为 secondary 反向到 Template（与上方 Template.rules 对称）。
    # 原先此处也指向关联实体 TemplateRule，已不再需要——TemplateService.bind/unbind
    # 由 TemplateRepository 显式操作 template_rule 行。
    templates: Mapped[List["Template"]] = relationship(
        "Template",
        secondary="template_rule",
        back_populates="rules",
        passive_deletes=True,
        viewonly=True,
    )

    __table_args__ = (
        CheckConstraint(
            "type IN ('CONDITION', 'TRANSFORM')",
            name="ck_rule_type_enum",
        ),
        Index("idx_rule_type", "type"),
        Index("idx_rule_active", "is_active"),
    )


# ============================================================
# Attribute（选项 / 公式）
# ============================================================

class Attribute(Base, TimestampMixin):
    """属性（一个选项 / 一段公式）

    字段：
    - name: 选项名 / 区间名
    - group_code: 技术 key（前端 GROUP BY 用）
    - group_name: 显示名
    - type: CONDITION / TRANSFORM（与 rule.type 联动）
    - value: CONDITION 时为空串，TRANSFORM 时为公式（含 input 变量）
    - input_min: TRANSFORM 半开半闭下限（null=无限制）
    - input_max: TRANSFORM 半开半闭上限（null=无限制）
    - sort_order: 同 group 内排序
    - description: 备注
    - is_active: 软启用
    """
    __tablename__ = "attribute"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    group_code: Mapped[str] = mapped_column(String(50), nullable=False)
    group_name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=AttributeType.CONDITION.value,
    )
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=False, default="")
    input_min: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    input_max: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # 关系
    rules: Mapped[List["Rule"]] = relationship(
        "Rule",
        secondary="rule_attribute",
        back_populates="attributes",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint(
            "type IN ('CONDITION', 'TRANSFORM')",
            name="ck_attribute_type_enum",
        ),
        Index("idx_attribute_group", "group_code"),
        Index("idx_attribute_active", "is_active"),
    )


# ============================================================
# TemplateRule（template ↔ rule 极简关联表）
# ============================================================

class TemplateRule(Base, TimestampMixin):
    """template ↔ rule 多对多关联（极简，不带 sort_order）

    rule 全局排序由 rule.sort_order 决定；本表只承担"绑定事实"。
    """
    __tablename__ = "template_rule"

    template_id: Mapped[int] = mapped_column(
        ForeignKey("template.id", ondelete="CASCADE"),
        nullable=False,
    )
    rule_id: Mapped[int] = mapped_column(
        ForeignKey("rule.id"),
        nullable=False,
    )

    # 注意：v4 改造后，Template.rules / Rule.templates 已通过 secondary 直连，
    # 此处不再保留 template / rule 反向 relationship（避免与 secondary 关系冲突）。
    # TemplateRule 仅作为"绑定事实"关联表存在，repository 层显式写入。
    # 关联表本身仍可用 .template_id / .rule_id 列做按需查询。

    __table_args__ = (
        UniqueConstraint("template_id", "rule_id", name="uk_template_rule"),
        Index("idx_template_rule_template", "template_id"),
        Index("idx_template_rule_rule", "rule_id"),
    )


# ============================================================
# RuleAttribute（rule ↔ attribute 极简关联表）
# ============================================================

class RuleAttribute(Base, TimestampMixin):
    """rule ↔ attribute 多对多关联（极简，不带 sort_order）

    attribute 排序由 attribute.sort_order 决定；本表只承担"绑定事实"。
    service 层校验：rule.type == attribute.type（v4 唯一硬校验）。
    """
    __tablename__ = "rule_attribute"

    rule_id: Mapped[int] = mapped_column(
        ForeignKey("rule.id", ondelete="CASCADE"),
        nullable=False,
    )
    attribute_id: Mapped[int] = mapped_column(
        ForeignKey("attribute.id", ondelete="CASCADE"),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("rule_id", "attribute_id", name="uk_rule_attribute"),
        Index("idx_rule_attribute_rule", "rule_id"),
        Index("idx_rule_attribute_attribute", "attribute_id"),
    )