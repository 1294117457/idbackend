"""需求申请表"""
from sqlalchemy import String, Integer, ForeignKey, JSON, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional
from datetime import datetime

from .base import Base, TimestampMixin


class DemandApplication(Base, TimestampMixin):
    """需求申请表"""
    __tablename__ = "demand_applications"

    student_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    application_data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    submit_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, default=None)
