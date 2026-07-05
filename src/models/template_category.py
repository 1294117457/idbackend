"""模板分类树模型（Layer 1）

职责：定义分类层级和各级分值上限，纯配置数据。
`is_bind_template` 字段唯一作用是标识"该节点已绑定 Template"——
    TRUE  = 已绑 template（不可再绑，也不能再加子节点）
    FALSE = 未绑 template（可绑 template，也可加子节点）
新增/绑定/解绑 template 时由 service 层显式修改。

详见 docs/core-function/四层职责设计.md 与 docs/core-function/template_category.md
"""
from sqlalchemy import (
    String,
    Integer,
    ForeignKey,
    Text,
    Boolean,
    DECIMAL,
    CheckConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List

from .base import Base, TimestampMixin


class TemplateCategory(Base, TimestampMixin):
    """模板分类树表（template_category）

    字段约束：
    - name: 同级下唯一（service 层校验）
    - max_score: NOT NULL 且 >= 0（DB 层 CHECK 兜底）
    - is_bind_template: TRUE=已绑 template（不可再加子，不可再绑 template）；
                        FALSE=未绑 template（可加子，可绑 template）。
                        不再由"是否有子节点"维护，service 在绑/解绑 template 时维护。
    - is_active: FALSE 时该节点在 get_tree 中不返回，但历史 application 不受影响
    """
    __tablename__ = "template_category"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("template_category.id", ondelete="CASCADE"),
        nullable=True,
    )
    max_score: Mapped[float] = mapped_column(DECIMAL(5, 2), nullable=False)
    is_bind_template: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[Optional[str]] = mapped_column(String(255))

    # 自关联：children/parent（service 层组装树时使用）
    children: Mapped[List["TemplateCategory"]] = relationship(
        "TemplateCategory",
        back_populates="parent",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    parent: Mapped[Optional["TemplateCategory"]] = relationship(
        "TemplateCategory", back_populates="children", remote_side="TemplateCategory.id"
    )

    # 反向关联：绑到本节点的 template（ON DELETE CASCADE 自动级联）
    templates: Mapped[List["Template"]] = relationship(
        "Template",
        back_populates="category",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint("max_score >= 0", name="ck_template_category_max_score_nonneg"),
        Index("idx_template_category_parent_sort", "parent_id", "sort_order", "id"),
        Index("idx_template_category_active", "is_active"),
    )