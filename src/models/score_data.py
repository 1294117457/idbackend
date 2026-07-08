"""分数流水模型（v4.2）

记录 application → PASSED 的"叶子分类贡献"，用于 recalculate 聚合。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    String, Integer, ForeignKey, DECIMAL, Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class ScoreData(Base, TimestampMixin):
    """分数流水表（v4.2）

    每个 PASSED 的 application 写一条流水：
      - score = application.apply_score 快照（不是 gain_score）
      - category_id 是 template_category 的叶子节点
      - is_active=FALSE = 外部标记失效（recalculate 时排除）

    recalculate 用 `category_id GROUP BY` 一条 SQL 拿到该学生所有叶子分类的原始总分。
    """
    __tablename__ = "score_data"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
    )
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"),
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("template_category.id"),
    )
    name: Mapped[Optional[str]] = mapped_column(String(100))   # 模板名快照
    score: Mapped[Decimal] = mapped_column(DECIMAL(5, 2))
    is_active: Mapped[bool] = mapped_column(default=True)

    __table_args__ = (
        Index("idx_score_data_user_active", "user_id", "is_active"),
        Index("idx_score_data_user_category", "user_id", "category_id"),
        Index("idx_score_data_application", "application_id"),
    )