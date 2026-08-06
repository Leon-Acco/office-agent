"""
协作任务模型
对应协作会议室的任务卡与子任务分配
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class TaskCard(Base):
    """
    协作任务卡
    状态：in_progress / completed / failed
    """
    __tablename__ = "task_card"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    state: Mapped[str] = mapped_column(String(20), default="in_progress")  # in_progress/completed
    initiator: Mapped[str] = mapped_column(String(100), default="")  # 发起人/角色
    deadline_minutes: Mapped[int] = mapped_column(Integer, default=30)  # 超时时间
    tags: Mapped[list] = mapped_column(JSON, default=list)  # 如 release/2.14
    conflict_note: Mapped[str | None] = mapped_column(Text, nullable=True)  # 冲突/汇总提示
    result_doc_path: Mapped[str | None] = mapped_column(String(500), nullable=True)  # 完整方案 md 文件名（collab_docs 下）
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    assignments: Mapped[list["TaskAssignment"]] = relationship(back_populates="task_card", cascade="all, delete-orphan")


class TaskAssignment(Base):
    """
    任务子项：分配给具体员工的子任务
    状态：analyzing(草案中) -> submitted(草案完成) -> discussing(互评中) -> discussed(互评完成)；clarify 为失败/超时态
    """
    __tablename__ = "task_assignment"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    task_card_id: Mapped[str] = mapped_column(String(32), ForeignKey("task_card.id"))
    agent_id: Mapped[str] = mapped_column(String(32), ForeignKey("agent.id"))
    agent_name: Mapped[str] = mapped_column(String(100))
    agent_emoji: Mapped[str] = mapped_column(String(10), default="🧑‍💻")
    department: Mapped[str] = mapped_column(String(100), default="")
    domain: Mapped[str] = mapped_column(String(100), default="")

    subtask_title: Mapped[str] = mapped_column(String(300))
    subtask_detail: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="analyzing")  # analyzing/submitted/discussing/discussed/clarify
    discussion_note: Mapped[str | None] = mapped_column(Text, nullable=True)  # 第 2 轮互评内容（站在本岗位对他人草案的补充/质疑/完善）
    confidence: Mapped[str | None] = mapped_column(String(20), nullable=True)  # HIGH/MEDIUM/LOW
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    task_card: Mapped["TaskCard"] = relationship(back_populates="assignments")
