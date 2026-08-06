"""
AI 员工模型 + 岗位包
对应 PRD 中 Agent 状态机与 RolePack 配置
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class RolePack(Base):
    """岗位包：版本化的 Agent 配置模板"""
    __tablename__ = "role_pack"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(20), default="1.0.0")
    owner: Mapped[str] = mapped_column(String(100), default="")
    # YAML/JSON 格式的完整岗位配置
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    agents: Mapped[list["Agent"]] = relationship(back_populates="role_pack")


class Agent(Base):
    """
    AI 员工（Agent）
    状态机：draft → indexing → pending_check → trial → online → maintenance / retired
    """
    __tablename__ = "agent"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(200))  # 如"订单域研发员工"
    emoji: Mapped[str] = mapped_column(String(10), default="🧑‍💻")

    # 归属关系
    department_id: Mapped[str] = mapped_column(String(32), ForeignKey("department.id"))
    domain_id: Mapped[str] = mapped_column(String(32), ForeignKey("domain.id"))

    # 岗位包
    role_pack_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("role_pack.id"), nullable=True)

    # 状态与版本
    status: Mapped[str] = mapped_column(String(20), default="online")  # online/indexing/trial/pending_check/maintenance
    version: Mapped[int] = mapped_column(Integer, default=1)
    owner: Mapped[str] = mapped_column(String(100), default="")

    # 描述信息
    description: Mapped[str] = mapped_column(Text, default="")
    resources: Mapped[list] = mapped_column(JSON, default=list)  # 关联资源列表
    tags: Mapped[list] = mapped_column(JSON, default=list)  # 部门/领域 Badge

    # Harness Engineering：行为准则 + 直绑能力（skill_key 列表，优先于 RolePack.config.skills）
    agents_md: Mapped[str] = mapped_column(Text, default="")
    skills: Mapped[list] = mapped_column(JSON, default=list)

    # 指标
    adoption_rate: Mapped[int] = mapped_column(Integer, default=0)  # 采纳率 %
    session_count: Mapped[int] = mapped_column(Integer, default=0)  # 会话总数

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # 关联
    domain: Mapped["Domain"] = relationship(back_populates="agents")
    role_pack: Mapped[RolePack | None] = relationship(back_populates="agents")

    @property
    def status_label(self) -> str:
        """状态中文标签"""
        labels = {
            "online": "可用",
            "indexing": "索引中",
            "trial": "试运行",
            "pending_check": "待校验",
            "maintenance": "维护中",
            "restricted": "受限",
        }
        return labels.get(self.status, self.status)
