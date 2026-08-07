"""
资源中心 / 能力中心 / 工具中心 数据模型
对应管理与治理页的 3 个 Tab
增强：Tool/Skill 加版本/状态/风险等级（对齐 LLD §3.1）
      AuditLog 加 trace_id/decision/rule_ids（对齐 LLD §3.2）
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base, now_cn


def _uuid() -> str:
    return uuid.uuid4().hex


class Resource(Base):
    """资源（代码仓库 / API 文档 / 数据集 / 知识库）"""
    __tablename__ = "resource"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(20), default="document")  # service/document/dataset/knowledge
    icon: Mapped[str] = mapped_column(String(10), default="📄")
    description: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="ready")  # ready/indexing/pending
    owner: Mapped[str] = mapped_column(String(100), default="")
    # 上传文档解析后的 Markdown 全文(入库后跨机可读,不再依赖各机本地 uploads 目录)
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_cn)


class Skill(Base):
    """
    能力（Skill）-- 声明式工作流清单
    增强（对齐 LLD §3.1）：version / state / precondition / risk_level
    state: DRAFT | IN_REVIEW | CANARY | RELEASED | RETIRED
    """
    __tablename__ = "skill"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(20), default="search")  # search/analysis/generation/api
    description: Mapped[str] = mapped_column(Text, default="")
    config: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON 配置（Manifest）
    owner: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(20), default="active")  # 兼容旧字段

    # LLD 增强：版本治理
    skill_key: Mapped[str] = mapped_column(String(128), default="")  # 如 call-chain
    version: Mapped[str] = mapped_column(String(32), default="1.0.0")
    state: Mapped[str] = mapped_column(String(24), default="RELEASED")  # DRAFT/IN_REVIEW/CANARY/RELEASED/RETIRED
    precondition: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 前置条件
    risk_level: Mapped[str] = mapped_column(String(16), default="LOW")  # LOW/MEDIUM/HIGH
    test_samples_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)  # 测试样本引用
    instructions: Mapped[str] = mapped_column(Text, default="")  # SKILL.md 式 markdown 指令体

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_cn)


class Tool(Base):
    """
    工具（MCP Tool）-- Agent 可调用的外部工具
    增强（对齐 LLD §3.1）：version / state / risk_level / mode / timeout
    state: REGISTERED | APPROVED | DISABLED
    mode: READ_ONLY | WRITE
    """
    __tablename__ = "tool"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(20), default="mcp")  # mcp/api/internal
    endpoint: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    config: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON 配置
    read_only: Mapped[str] = mapped_column(String(5), default="true")  # 兼容旧字段
    owner: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(20), default="active")  # 兼容旧字段

    # LLD 增强：版本治理
    tool_key: Mapped[str] = mapped_column(String(128), default="")  # 如 searchCode
    version: Mapped[str] = mapped_column(String(32), default="1.0.0")
    state: Mapped[str] = mapped_column(String(16), default="APPROVED")  # REGISTERED/APPROVED/DISABLED
    mode: Mapped[str] = mapped_column(String(16), default="READ_ONLY")  # READ_ONLY/WRITE
    risk_level: Mapped[str] = mapped_column(String(16), default="LOW")  # LOW/MEDIUM/HIGH
    timeout_ms: Mapped[int] = mapped_column(Integer, default=5000)
    required_permissions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    input_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_cn)


class AuditLog(Base):
    """
    审计日志
    增强（对齐 LLD §3.2）：trace_id / decision / rule_ids / resource_hash
    """
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    actor: Mapped[str] = mapped_column(String(100), default="system")
    action: Mapped[str] = mapped_column(String(50))  # create/update/delete/login/ask
    target_type: Mapped[str] = mapped_column(String(50), default="")  # agent/department/knowledge...
    target_id: Mapped[str] = mapped_column(String(32), default="")
    target_name: Mapped[str] = mapped_column(String(200), default="")
    detail: Mapped[str] = mapped_column(Text, default="")

    # LLD 增强：可追溯性
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 链路追踪 ID
    decision: Mapped[str | None] = mapped_column(String(16), nullable=True)  # ALLOW/DENY/MASK
    rule_ids: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 命中的策略规则 ID 列表
    resource_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 资源哈希（脱敏）
    commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)  # Git commit SHA

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_cn)
