"""
治理域数据模型（对齐 LLD §3）
包含：岗位包版本状态机 / 变更审批引擎 / 策略中心 / 治理角色
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base, now_cn


def _uuid() -> str:
    return uuid.uuid4().hex


# ═══════════════════════════════════════════════
#  1. 岗位包版本治理（LLD §3.1）
# ═══════════════════════════════════════════════

class RolePackVersion(Base):
    """
    岗位包版本（状态机）
    DRAFT -> IN_REVIEW -> CANARY -> RELEASED -> RETIRED
                    ↓           ↓
               ROLLED_BACK  ROLLED_BACK
    """
    __tablename__ = "role_pack_version"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    role_pack_id: Mapped[str] = mapped_column(String(32), index=True)  # 关联 role_pack.id
    version: Mapped[str] = mapped_column(String(32))  # 语义化版本 1.0.0
    checksum: Mapped[str] = mapped_column(String(64), default="")  # YAML 规范化后的 SHA-256

    # 完整岗位包定义（scope/skills/tools/modelPolicy/escalation）
    spec: Mapped[dict] = mapped_column(JSON, default=dict)

    # 状态机：DRAFT | IN_REVIEW | CANARY | RELEASED | ROLLED_BACK | RETIRED
    state: Mapped[str] = mapped_column(String(24), default="DRAFT")

    # 灰度范围：{ tenantIds: [], repoIds: [], percentage: 5 }
    rollout: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    eval_report_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    published_by: Mapped[str] = mapped_column(String(100), default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_cn)


# ═══════════════════════════════════════════════
#  2. 变更审批引擎（LLD §3.2）
# ═══════════════════════════════════════════════

class ChangeRequest(Base):
    """
    变更审批单
    target_type: ROLE_PACK | TOOL | SKILL | POLICY | KNOWLEDGE | DOCUMENT | RELEASE
    action: CREATE | UPDATE | PUBLISH | ROLLBACK | RETIRE | APPROVE_KNOWLEDGE
    approval_policy: SINGLE | DUAL | QUORUM
    state: PENDING | APPROVED | REJECTED | APPLIED | FAILED
    """
    __tablename__ = "change_request"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    target_type: Mapped[str] = mapped_column(String(32))  # ROLE_PACK/TOOL/SKILL/POLICY/KNOWLEDGE/DOCUMENT/RELEASE
    target_id: Mapped[str] = mapped_column(String(32))  # 目标实体 ID
    action: Mapped[str] = mapped_column(String(32))  # CREATE/UPDATE/PUBLISH/ROLLBACK/RETIRE

    # 变更前后快照或补丁
    diff: Mapped[dict] = mapped_column(JSON, default=dict)

    approval_policy: Mapped[str] = mapped_column(String(24), default="SINGLE")  # SINGLE/DUAL/QUORUM
    state: Mapped[str] = mapped_column(String(24), default="PENDING")  # PENDING/APPROVED/REJECTED/APPLIED/FAILED

    requested_by: Mapped[str] = mapped_column(String(100), default="admin")
    reason: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_cn)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_cn,
                                                   onupdate=now_cn)


class ChangeApproval(Base):
    """
    审批记录（一个 ChangeRequest 可有多条审批）
    decision: APPROVE | REJECT
    """
    __tablename__ = "change_approval"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    change_request_id: Mapped[str] = mapped_column(String(32), index=True)
    approver_id: Mapped[str] = mapped_column(String(100))  # 审批人
    approver_role: Mapped[str] = mapped_column(String(50), default="")  # 治理角色
    decision: Mapped[str] = mapped_column(String(16))  # APPROVE/REJECT
    comment: Mapped[str] = mapped_column(Text, default="")
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_cn)


# ═══════════════════════════════════════════════
#  3. 策略中心（LLD §3.2）
# ═══════════════════════════════════════════════

class PolicyRule(Base):
    """
    策略规则（版本化、可回溯）
    category: ACL | REDACTION | BUDGET | TOOL_RISK
    state: ACTIVE | DISABLED
    """
    __tablename__ = "policy_rule"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    category: Mapped[str] = mapped_column(String(24))  # ACL/REDACTION/BUDGET/TOOL_RISK
    rule_key: Mapped[str] = mapped_column(String(128))  # 规则唯一键
    definition: Mapped[dict] = mapped_column(JSON, default=dict)  # 规则定义
    version: Mapped[int] = mapped_column(Integer, default=1)  # 版本号（追加式）
    state: Mapped[str] = mapped_column(String(16), default="ACTIVE")  # ACTIVE/DISABLED
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_cn)


# ═══════════════════════════════════════════════
#  4. 治理角色（LLD §4）
# ═══════════════════════════════════════════════

class GovRole(Base):
    """
    治理角色（独立于业务 ACL）
    role: platform-admin | rolepack-owner | knowledge-reviewer | security-reviewer | auditor
    """
    __tablename__ = "gov_role"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(100), index=True)  # 用户标识
    role: Mapped[str] = mapped_column(String(50))  # 治理角色
    scope: Mapped[str] = mapped_column(String(100), default="*")  # 作用范围（部门/领域/*）
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_cn)


# ═══════════════════════════════════════════════
#  5. 仓库 + Agent-仓库绑定（LLD §12.8）
# ═══════════════════════════════════════════════

class Repository(Base):
    """
    Git 仓库
    state: CONNECTING | CONNECTED | INDEXING | READY | DEGRADED | FAILED
    """
    __tablename__ = "repository"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255))
    provider: Mapped[str] = mapped_column(String(32), default="gitlab")  # gitlab/github/gitea
    clone_url: Mapped[str] = mapped_column(String(1024))
    default_branch: Mapped[str] = mapped_column(String(255), default="main")
    credential_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)  # Vault/KMS 引用
    acl_source: Mapped[str] = mapped_column(String(32), default="MANUAL")  # PROVIDER_SYNC/MANUAL
    languages: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    state: Mapped[str] = mapped_column(String(24), default="CONNECTING")
    owner: Mapped[str] = mapped_column(String(100), default="")
    # 仓库一句话职责说明,由 build_system_prompt 动态渲染进「绑定仓库+说明」,
    # 取代 agents_md 里手写的易漂移仓库清单
    description: Mapped[str] = mapped_column(Text, default="")
    # 定时自动拉取间隔(分钟),NULL/0=关闭(第 7 轮需求:仓库定时刷新)
    auto_refresh_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 上次同步(拉取)时间,手动 pull / 定时刷新都会更新
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_cn)


class AgentRepoBinding(Base):
    """Agent-仓库绑定（多对多）"""
    __tablename__ = "agent_repo_binding"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    agent_id: Mapped[str] = mapped_column(String(32), index=True)
    repo_id: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_cn)
