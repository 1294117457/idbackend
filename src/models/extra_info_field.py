"""学生扩展字段模型（extra_info_field）

设计说明：
- id 作为 stable key，extra_info 用 f_{id} 做 key（如 f_1、f_2）
- name / type / options 由老师在后端配置，学生端动态渲染
- is_active=FALSE 时管理端列表不展示，学生端也不展示（不删存量数据）

详见 docs/core-function/extra_info_field.md
"""
from sqlalchemy import String, Integer, Boolean, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional, List

from .base import Base, TimestampMixin


class ExtraInfoField(Base, TimestampMixin):
    """extra_info_field 表"""
    __tablename__ = "extra_info_field"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="TEXT"
    )
    options: Mapped[list] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    description: Mapped[Optional[str]] = mapped_column(String(255))

    __table_args__ = (
        Index("idx_extra_info_field_sort", "sort_order", "id"),
        Index("idx_extra_info_field_active", "is_active"),
    )

    def get_field_key(self) -> str:
        """返回 extra_info 中使用的 key，如 'f_1'"""
        return f"f_{self.id}"
