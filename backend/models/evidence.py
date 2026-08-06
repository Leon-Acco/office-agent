"""
证据模型
对应 Agent 回答中附带的可追溯证据卡
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, Integer, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class Evidence(Base):
    """
    证据卡：每条结论必须绑定至少一个证据
    source_type: CODE / DOC / GRAPH / CONFIG
    """
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    agent_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("agent.id"), nullable=True)
    source_type: Mapped[str] = mapped_column(String(20), default="CODE")  # CODE/DOC/GRAPH/CONFIG
    source_ref: Mapped[str] = mapped_column(String(500), default="")  # 文件路径/文档名
    excerpt: Mapped[str] = mapped_column(Text, default="")  # 证据片段
    verification_status: Mapped[str] = mapped_column(String(20), default="VERIFIED")  # VERIFIED/UNVERIFIED
    line_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
