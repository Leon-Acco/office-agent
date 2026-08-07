"""
组织架构模型：公司 → 部门 → 领域
对应 PRD 四层组织模型的前三层
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base, now_cn


def _uuid() -> str:
    return uuid.uuid4().hex


class Company(Base):
    """公司实体"""
    __tablename__ = "company"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_cn)

    departments: Mapped[list["Department"]] = relationship(back_populates="company")


class Department(Base):
    """部门实体"""
    __tablename__ = "department"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    company_id: Mapped[str] = mapped_column(String(32), ForeignKey("company.id"))
    name: Mapped[str] = mapped_column(String(100))
    emoji: Mapped[str] = mapped_column(String(10), default="📦")
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_cn)

    company: Mapped["Company"] = relationship(back_populates="departments")
    domains: Mapped[list["Domain"]] = relationship(back_populates="department")


class Domain(Base):
    """领域实体（部门下的专业细分）"""
    __tablename__ = "domain"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    department_id: Mapped[str] = mapped_column(String(32), ForeignKey("department.id"))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_cn)

    department: Mapped["Department"] = relationship(back_populates="domains")
    agents: Mapped[list["Agent"]] = relationship(back_populates="domain")
