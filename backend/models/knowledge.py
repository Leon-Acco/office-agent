"""
知识候选模型
对应"知识与案例"页面，沉淀经审核的指南/FAQ/结论
增强（对齐 LLD §3.3）：scope / evidence_ids / commit_sha / expires_at / 审核状态机
状态机：SUBMITTED -> IN_REVIEW -> APPROVED / REJECTED
                          APPROVED -> EXPIRED -> IN_REVIEW
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base, now_cn


def _uuid() -> str:
    return uuid.uuid4().hex


class KnowledgeCandidate(Base):
    """
    知识候选条目
    状态：SUBMITTED | IN_REVIEW | APPROVED | REJECTED | EXPIRED
    审核通过后才参与共享检索
    """
    __tablename__ = "knowledge_candidate"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(300))
    domain: Mapped[str] = mapped_column(String(100))  # 所属领域
    department: Mapped[str] = mapped_column(String(100))  # 所属部门
    icon: Mapped[str] = mapped_column(String(10), default="📘")

    # 兼容旧字段
    status: Mapped[str] = mapped_column(String(20), default="pending_review")  # published/expired/pending_review
    owner: Mapped[str] = mapped_column(String(100), default="")
    confidence: Mapped[str] = mapped_column(String(10), default="MEDIUM")  # HIGH/MEDIUM/LOW
    published_at: Mapped[str] = mapped_column(String(20), default="")  # 如 2026-07-14
    conflict_warning: Mapped[str | None] = mapped_column(Text, nullable=True)

    # LLD 增强：审核治理
    state: Mapped[str] = mapped_column(String(24), default="SUBMITTED")  # SUBMITTED/IN_REVIEW/APPROVED/REJECTED/EXPIRED
    scope: Mapped[str] = mapped_column(String(24), default="PROJECT")  # PROJECT/DEPARTMENT/COMPANY
    body_md: Mapped[str] = mapped_column(Text, default="")  # 正文 Markdown
    evidence_ids: Mapped[dict] = mapped_column(JSON, default=list)  # 证据 ID 列表
    commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)  # 绑定的 Git SHA
    source_session_id: Mapped[str | None] = mapped_column(String(32), nullable=True)  # 来源会话
    source_answer_id: Mapped[str | None] = mapped_column(String(32), nullable=True)  # 来源回答
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 失效时间
    reviewed_by: Mapped[str] = mapped_column(String(100), default="")  # 审核人

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_cn)
