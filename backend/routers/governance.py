"""
治理域 API 路由（对齐 LLD §6）
包含：变更审批 / 策略中心 / 岗位包版本 / 知识审核 / 仓库管理 / 运营看板
"""
import hashlib
import json
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.governance import (
    RolePackVersion, ChangeRequest, ChangeApproval, PolicyRule, GovRole,
    Repository, AgentRepoBinding,
)
from backend.models.resource import Tool, Skill, AuditLog
from backend.models.knowledge import KnowledgeCandidate
from backend.models.agent import RolePack, Agent

router = APIRouter(prefix="/api/gov", tags=["governance"])


def _uuid() -> str:
    return uuid4().hex


# ═══════════════════════════════════════════════
#  1. 变更审批引擎（LLD §5.2）
# ═══════════════════════════════════════════════

class ChangeRequestBody(BaseModel):
    target_type: str  # ROLE_PACK/TOOL/SKILL/POLICY/KNOWLEDGE/DOCUMENT/RELEASE
    target_id: str
    action: str  # CREATE/UPDATE/PUBLISH/ROLLBACK/RETIRE
    diff: dict = {}
    approval_policy: str = "SINGLE"  # SINGLE/DUAL/QUORUM
    reason: str = ""
    requested_by: str = "admin"


class ApprovalBody(BaseModel):
    approver_id: str
    approver_role: str = ""
    decision: str  # APPROVE/REJECT
    comment: str = ""


@router.get("/change-requests")
async def list_change_requests(
    state: Optional[str] = Query(None),
    target_type: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    """变更单列表（可按状态/目标过滤）"""
    query = select(ChangeRequest).order_by(ChangeRequest.created_at.desc()).limit(limit)
    if state:
        query = query.where(ChangeRequest.state == state)
    if target_type:
        query = query.where(ChangeRequest.target_type == target_type)
    crs = (await db.execute(query)).scalars().all()
    return [
        {
            "id": cr.id, "target_type": cr.target_type, "target_id": cr.target_id,
            "action": cr.action, "approval_policy": cr.approval_policy,
            "state": cr.state, "requested_by": cr.requested_by, "reason": cr.reason,
            "diff": cr.diff, "created_at": cr.created_at.strftime("%Y-%m-%d %H:%M:%S") if cr.created_at else "",
        }
        for cr in crs
    ]


@router.post("/change-requests")
async def create_change_request(body: ChangeRequestBody, db: AsyncSession = Depends(get_db)):
    """提交变更单"""
    cr = ChangeRequest(
        id=_uuid(), target_type=body.target_type, target_id=body.target_id,
        action=body.action, diff=body.diff, approval_policy=body.approval_policy,
        state="PENDING", requested_by=body.requested_by, reason=body.reason,
    )
    db.add(cr)
    await db.flush()
    db.add(AuditLog(id=_uuid(), actor=body.requested_by, action="create",
                   target_type="change_request", target_id=cr.id,
                   target_name=f"{body.action} {body.target_type}", detail=body.reason))
    await db.flush()
    return {"id": cr.id, "state": "PENDING", "approval_policy": body.approval_policy}


@router.post("/change-requests/{cr_id}/decision")
async def approve_change_request(cr_id: str, body: ApprovalBody, db: AsyncSession = Depends(get_db)):
    """批准/驳回变更单"""
    cr = (await db.execute(select(ChangeRequest).where(ChangeRequest.id == cr_id))).scalar_one_or_none()
    if not cr:
        raise HTTPException(404, "变更单不存在")
    if cr.state != "PENDING":
        raise HTTPException(400, f"变更单当前状态 {cr.state}，不可审批")

    # 记录审批
    approval = ChangeApproval(
        id=_uuid(), change_request_id=cr_id, approver_id=body.approver_id,
        approver_role=body.approver_role, decision=body.decision, comment=body.comment,
    )
    db.add(approval)
    await db.flush()

    # DUAL 双人复核：检查是否满足人数
    if cr.approval_policy == "DUAL":
        approvals = (await db.execute(
            select(ChangeApproval).where(
                and_(ChangeApproval.change_request_id == cr_id,
                     ChangeApproval.decision == "APPROVE")
            )
        )).scalars().all()
        if len(approvals) >= 2:
            cr.state = "APPROVED"
        elif body.decision == "REJECT":
            cr.state = "REJECTED"
    else:  # SINGLE
        if body.decision == "APPROVE":
            cr.state = "APPROVED"
        else:
            cr.state = "REJECTED"

    await db.flush()
    db.add(AuditLog(id=_uuid(), actor=body.approver_id, action="approve" if body.decision == "APPROVE" else "reject",
                   target_type="change_request", target_id=cr_id,
                   detail=f"审批 {body.decision}: {body.comment}"))
    await db.flush()
    return {"state": cr.state, "message": f"变更单已{('批准' if body.decision == 'APPROVE' else '驳回')}"}


# ═══════════════════════════════════════════════
#  2. 岗位包版本治理（LLD §5.1）
# ═══════════════════════════════════════════════

class RolePackVersionBody(BaseModel):
    role_pack_id: str
    version: str
    spec: dict = {}
    published_by: str = "admin"


@router.get("/role-pack-versions/{role_pack_id}")
async def list_pack_versions(role_pack_id: str, db: AsyncSession = Depends(get_db)):
    """列出岗位包的所有版本"""
    versions = (await db.execute(
        select(RolePackVersion).where(RolePackVersion.role_pack_id == role_pack_id)
        .order_by(RolePackVersion.created_at.desc())
    )).scalars().all()
    return [
        {
            "id": v.id, "version": v.version, "state": v.state,
            "checksum": v.checksum, "spec": v.spec, "rollout": v.rollout,
            "published_by": v.published_by,
            "published_at": v.published_at.strftime("%Y-%m-%d %H:%M:%S") if v.published_at else "",
            "created_at": v.created_at.strftime("%Y-%m-%d %H:%M:%S") if v.created_at else "",
        }
        for v in versions
    ]


@router.post("/role-pack-versions")
async def create_pack_version(body: RolePackVersionBody, db: AsyncSession = Depends(get_db)):
    """创建岗位包草稿版本"""
    # 计算 checksum
    spec_str = json.dumps(body.spec, sort_keys=True)
    checksum = hashlib.sha256(spec_str.encode()).hexdigest()

    v = RolePackVersion(
        id=_uuid(), role_pack_id=body.role_pack_id, version=body.version,
        checksum=checksum, spec=body.spec, state="DRAFT", published_by=body.published_by,
    )
    db.add(v)
    await db.flush()
    db.add(AuditLog(id=_uuid(), actor=body.published_by, action="create",
                   target_type="role_pack_version", target_id=v.id,
                   target_name=f"v{body.version}", detail=f"创建岗位包草稿版本 {body.version}"))
    await db.flush()
    return {"id": v.id, "state": "DRAFT", "checksum": checksum}


class PublishBody(BaseModel):
    version_id: str
    rollout: dict = {}  # 灰度范围
    published_by: str = "admin"


@router.post("/role-pack-versions/{version_id}/publish")
async def publish_pack_version(version_id: str, body: PublishBody, db: AsyncSession = Depends(get_db)):
    """提交发布（进入审批 + 灰度）"""
    v = (await db.execute(select(RolePackVersion).where(RolePackVersion.id == version_id))).scalar_one_or_none()
    if not v:
        raise HTTPException(404, "版本不存在")
    if v.state not in ("DRAFT", "ROLLED_BACK"):
        raise HTTPException(400, f"版本当前状态 {v.state}，不可发布")

    # 创建变更审批单
    cr = ChangeRequest(
        id=_uuid(), target_type="ROLE_PACK", target_id=v.role_pack_id,
        action="PUBLISH", diff={"version_id": version_id, "rollout": body.rollout},
        approval_policy="DUAL", state="PENDING",
        requested_by=body.published_by, reason=f"发布岗位包版本 {v.version}",
    )
    db.add(cr)
    v.state = "IN_REVIEW"
    await db.flush()

    db.add(AuditLog(id=_uuid(), actor=body.published_by, action="publish",
                   target_type="role_pack_version", target_id=version_id,
                   target_name=f"v{v.version}", detail=f"提交发布，审批单 {cr.id}"))
    await db.flush()
    return {"change_request_id": cr.id, "state": "IN_REVIEW", "message": "已提交审批"}


@router.post("/role-pack-versions/{version_id}/canary")
async def canary_pack_version(version_id: str, body: PublishBody, db: AsyncSession = Depends(get_db)):
    """审批通过后进入灰度"""
    v = (await db.execute(select(RolePackVersion).where(RolePackVersion.id == version_id))).scalar_one_or_none()
    if not v:
        raise HTTPException(404, "版本不存在")
    if v.state != "IN_REVIEW":
        raise HTTPException(400, f"版本当前状态 {v.state}，需先审批通过")

    v.state = "CANARY"
    v.rollout = body.rollout
    v.published_by = body.published_by
    v.published_at = datetime.now(timezone.utc)
    await db.flush()

    db.add(AuditLog(id=_uuid(), actor=body.published_by, action="canary",
                   target_type="role_pack_version", target_id=version_id,
                   target_name=f"v{v.version}", detail=f"进入灰度: {body.rollout}"))
    await db.flush()
    return {"state": "CANARY", "message": "已进入灰度"}


@router.post("/role-pack-versions/{version_id}/release")
async def release_pack_version(version_id: str, published_by: str = "admin", db: AsyncSession = Depends(get_db)):
    """灰度达标后全量发布"""
    v = (await db.execute(select(RolePackVersion).where(RolePackVersion.id == version_id))).scalar_one_or_none()
    if not v:
        raise HTTPException(404, "版本不存在")
    if v.state != "CANARY":
        raise HTTPException(400, f"版本当前状态 {v.state}，需先灰度")

    v.state = "RELEASED"
    await db.flush()
    db.add(AuditLog(id=_uuid(), actor=published_by, action="release",
                   target_type="role_pack_version", target_id=version_id,
                   target_name=f"v{v.version}", detail="全量发布"))
    await db.flush()
    return {"state": "RELEASED", "message": "已全量发布"}


@router.post("/role-pack-versions/{version_id}/rollback")
async def rollback_pack_version(version_id: str, published_by: str = "admin", db: AsyncSession = Depends(get_db)):
    """回滚版本"""
    v = (await db.execute(select(RolePackVersion).where(RolePackVersion.id == version_id))).scalar_one_or_none()
    if not v:
        raise HTTPException(404, "版本不存在")
    old_state = v.state
    v.state = "ROLLED_BACK"
    await db.flush()
    db.add(AuditLog(id=_uuid(), actor=published_by, action="rollback",
                   target_type="role_pack_version", target_id=version_id,
                   target_name=f"v{v.version}", detail=f"从 {old_state} 回滚"))
    await db.flush()
    return {"state": "ROLLED_BACK", "message": "已回滚"}


# ═══════════════════════════════════════════════
#  3. 策略中心（LLD §5.2）
# ═══════════════════════════════════════════════

class PolicyRuleBody(BaseModel):
    category: str  # ACL/REDACTION/BUDGET/TOOL_RISK
    rule_key: str
    definition: dict
    effective_from: Optional[str] = None


@router.get("/policies")
async def list_policies(
    category: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """策略规则列表"""
    query = select(PolicyRule).order_by(PolicyRule.created_at.desc())
    if category:
        query = query.where(PolicyRule.category == category)
    if state:
        query = query.where(PolicyRule.state == state)
    rules = (await db.execute(query)).scalars().all()
    return [
        {
            "id": r.id, "category": r.category, "rule_key": r.rule_key,
            "definition": r.definition, "version": r.version, "state": r.state,
            "effective_from": r.effective_from.strftime("%Y-%m-%d %H:%M:%S") if r.effective_from else "",
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else "",
        }
        for r in rules
    ]


@router.post("/policies")
async def create_policy(body: PolicyRuleBody, db: AsyncSession = Depends(get_db)):
    """提交策略变更（进入审批）"""
    # 查询当前最大版本
    existing = (await db.execute(
        select(func.max(PolicyRule.version)).where(
            and_(PolicyRule.category == body.category, PolicyRule.rule_key == body.rule_key)
        )
    )).scalar() or 0

    r = PolicyRule(
        id=_uuid(), category=body.category, rule_key=body.rule_key,
        definition=body.definition, version=existing + 1, state="DISABLED",
    )
    if body.effective_from:
        r.effective_from = datetime.fromisoformat(body.effective_from)
    db.add(r)
    await db.flush()

    # 创建审批单
    cr = ChangeRequest(
        id=_uuid(), target_type="POLICY", target_id=r.id,
        action="UPDATE", diff={"category": body.category, "rule_key": body.rule_key, "version": r.version},
        approval_policy="DUAL", state="PENDING", requested_by="admin",
        reason=f"策略变更 {body.category}/{body.rule_key} v{r.version}",
    )
    db.add(cr)
    await db.flush()
    return {"id": r.id, "version": r.version, "change_request_id": cr.id, "message": "已提交审批"}


@router.post("/policies/{rule_id}/activate")
async def activate_policy(rule_id: str, db: AsyncSession = Depends(get_db)):
    """激活策略（审批通过后调用）"""
    r = (await db.execute(select(PolicyRule).where(PolicyRule.id == rule_id))).scalar_one_or_none()
    if not r:
        raise HTTPException(404, "策略不存在")
    # 禁用同 category+rule_key 的旧版本
    old_rules = (await db.execute(
        select(PolicyRule).where(
            and_(PolicyRule.category == r.category, PolicyRule.rule_key == r.rule_key,
                 PolicyRule.id != rule_id, PolicyRule.state == "ACTIVE")
        )
    )).scalars().all()
    for old in old_rules:
        old.state = "DISABLED"
    r.state = "ACTIVE"
    if not r.effective_from:
        r.effective_from = datetime.now(timezone.utc)
    await db.flush()
    db.add(AuditLog(id=_uuid(), actor="admin", action="activate",
                   target_type="policy_rule", target_id=rule_id,
                   target_name=f"{r.category}/{r.rule_key}", detail=f"激活 v{r.version}"))
    await db.flush()
    return {"state": "ACTIVE", "message": "策略已激活"}


# ═══════════════════════════════════════════════
#  4. 知识候选审核（LLD §5.3）
# ═══════════════════════════════════════════════

class KnowledgeReviewBody(BaseModel):
    decision: str  # APPROVE/REJECT
    reviewer: str = "admin"
    scope: str = "PROJECT"  # PROJECT/DEPARTMENT/COMPANY
    comment: str = ""


@router.get("/knowledge-candidates")
async def list_knowledge_candidates(
    state: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    """知识候选队列"""
    query = select(KnowledgeCandidate).order_by(KnowledgeCandidate.created_at.desc()).limit(limit)
    if state:
        query = query.where(KnowledgeCandidate.state == state)
    items = (await db.execute(query)).scalars().all()
    return [
        {
            "id": k.id, "title": k.title, "domain": k.domain, "department": k.department,
            "state": k.state, "scope": k.scope, "confidence": k.confidence,
            "owner": k.owner, "reviewed_by": k.reviewed_by,
            "expires_at": k.expires_at.strftime("%Y-%m-%d") if k.expires_at else "",
            "created_at": k.created_at.strftime("%Y-%m-%d %H:%M:%S") if k.created_at else "",
        }
        for k in items
    ]


@router.post("/knowledge-candidates/{kc_id}/review")
async def review_knowledge_candidate(kc_id: str, body: KnowledgeReviewBody, db: AsyncSession = Depends(get_db)):
    """审核知识候选"""
    kc = (await db.execute(select(KnowledgeCandidate).where(KnowledgeCandidate.id == kc_id))).scalar_one_or_none()
    if not kc:
        raise HTTPException(404, "知识候选不存在")
    if kc.state not in ("SUBMITTED", "IN_REVIEW", "EXPIRED"):
        raise HTTPException(400, f"当前状态 {kc.state}，不可审核")

    if body.decision == "APPROVE":
        kc.state = "APPROVED"
        kc.scope = body.scope  # 显式确认范围（越权升级防护）
        kc.reviewed_by = body.reviewer
        kc.status = "published"
        kc.published_at = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    else:
        kc.state = "REJECTED"
        kc.reviewed_by = body.reviewer
        kc.status = "expired"

    await db.flush()
    db.add(AuditLog(id=_uuid(), actor=body.reviewer, action="approve" if body.decision == "APPROVE" else "reject",
                   target_type="knowledge_candidate", target_id=kc_id,
                   target_name=kc.title, detail=f"审核 {body.decision}, scope={body.scope}, {body.comment}"))
    await db.flush()
    return {"state": kc.state, "message": f"知识候选已{('通过' if body.decision == 'APPROVE' else '驳回')}"}


# ═══════════════════════════════════════════════
#  5. 仓库管理（LLD §12.5 / §12.8）
# ═══════════════════════════════════════════════

class RepoBody(BaseModel):
    name: str
    provider: str = "gitlab"
    clone_url: str
    default_branch: str = "main"
    credential_ref: str = ""
    owner: str = ""


@router.get("/repositories")
async def list_repositories(db: AsyncSession = Depends(get_db)):
    """仓库列表（先增量登记 workspaces 里的本地目录，保证手工导入的仓库可被绑定）"""
    from backend.services.repo_registry import sync_workspace_repos
    await sync_workspace_repos(db)
    repos = (await db.execute(select(Repository).order_by(Repository.created_at.desc()))).scalars().all()
    return [
        {
            "id": r.id, "name": r.name, "provider": r.provider,
            "clone_url": r.clone_url, "default_branch": r.default_branch,
            "state": r.state, "owner": r.owner,
            "languages": r.languages,
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else "",
        }
        for r in repos
    ]


@router.post("/repositories")
async def create_repository(body: RepoBody, db: AsyncSession = Depends(get_db)):
    """接入仓库"""
    r = Repository(
        id=_uuid(), name=body.name, provider=body.provider,
        clone_url=body.clone_url, default_branch=body.default_branch,
        credential_ref=body.credential_ref or None, state="CONNECTED", owner=body.owner,
    )
    db.add(r)
    await db.flush()
    db.add(AuditLog(id=_uuid(), actor=body.owner or "admin", action="create",
                   target_type="repository", target_id=r.id, target_name=body.name,
                   detail=f"接入仓库 {body.clone_url}"))
    await db.flush()
    return {"id": r.id, "state": "CONNECTED", "message": "仓库已接入"}


@router.post("/agents/{agent_id}/repos/{repo_id}/bind")
async def bind_agent_repo(agent_id: str, repo_id: str, db: AsyncSession = Depends(get_db)):
    """绑定仓库给 Agent"""
    existing = (await db.execute(
        select(AgentRepoBinding).where(
            and_(AgentRepoBinding.agent_id == agent_id, AgentRepoBinding.repo_id == repo_id)
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(400, "已绑定")
    b = AgentRepoBinding(id=_uuid(), agent_id=agent_id, repo_id=repo_id)
    db.add(b)
    await db.flush()
    return {"message": "绑定成功"}


@router.get("/agents/{agent_id}/repos")
async def get_agent_repos(agent_id: str, db: AsyncSession = Depends(get_db)):
    """获取 Agent 绑定的仓库"""
    bindings = (await db.execute(
        select(AgentRepoBinding).where(AgentRepoBinding.agent_id == agent_id)
    )).scalars().all()
    repo_ids = [b.repo_id for b in bindings]
    if not repo_ids:
        return []
    repos = (await db.execute(select(Repository).where(Repository.id.in_(repo_ids)))).scalars().all()
    return [{"id": r.id, "name": r.name, "state": r.state, "provider": r.provider} for r in repos]


@router.delete("/agents/{agent_id}/repos/{repo_id}")
async def unbind_agent_repo(agent_id: str, repo_id: str, db: AsyncSession = Depends(get_db)):
    """解绑 Agent 的仓库"""
    existing = (await db.execute(
        select(AgentRepoBinding).where(
            and_(AgentRepoBinding.agent_id == agent_id, AgentRepoBinding.repo_id == repo_id)
        )
    )).scalar_one_or_none()
    if not existing:
        raise HTTPException(404, "绑定不存在")
    await db.delete(existing)
    await db.flush()
    return {"message": "解绑成功"}


# ═══════════════════════════════════════════════
#  6. 治理角色（LLD §4）
# ═══════════════════════════════════════════════

class GovRoleBody(BaseModel):
    user_id: str
    role: str  # platform-admin/rolepack-owner/knowledge-reviewer/security-reviewer/auditor
    scope: str = "*"


@router.get("/roles")
async def list_gov_roles(db: AsyncSession = Depends(get_db)):
    """治理角色列表"""
    roles = (await db.execute(select(GovRole))).scalars().all()
    return [
        {"id": r.id, "user_id": r.user_id, "role": r.role, "scope": r.scope,
         "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else ""}
        for r in roles
    ]


@router.post("/roles")
async def assign_gov_role(body: GovRoleBody, db: AsyncSession = Depends(get_db)):
    """分配治理角色"""
    r = GovRole(id=_uuid(), user_id=body.user_id, role=body.role, scope=body.scope)
    db.add(r)
    await db.flush()
    db.add(AuditLog(id=_uuid(), actor="admin", action="create",
                   target_type="gov_role", target_id=r.id,
                   target_name=f"{body.user_id}:{body.role}", detail=f"分配治理角色 {body.role}"))
    await db.flush()
    return {"id": r.id, "message": "角色已分配"}


# ═══════════════════════════════════════════════
#  7. 运营看板（LLD §8）
# ═══════════════════════════════════════════════

@router.get("/dashboards/{domain}")
async def get_dashboard(domain: str, db: AsyncSession = Depends(get_db)):
    """
    运营看板
    domain: governance | security | knowledge | version | cost
    """
    if domain == "governance":
        # 治理效率
        total_cr = (await db.execute(select(func.count(ChangeRequest.id)))).scalar() or 0
        pending_cr = (await db.execute(select(func.count(ChangeRequest.id)).where(ChangeRequest.state == "PENDING"))).scalar() or 0
        approved_cr = (await db.execute(select(func.count(ChangeRequest.id)).where(ChangeRequest.state == "APPROVED"))).scalar() or 0
        rejected_cr = (await db.execute(select(func.count(ChangeRequest.id)).where(ChangeRequest.state == "REJECTED"))).scalar() or 0
        return {
            "total": total_cr, "pending": pending_cr,
            "approved": approved_cr, "rejected": rejected_cr,
            "approval_rate": round(approved_cr / total_cr * 100, 1) if total_cr > 0 else 0,
        }

    if domain == "version":
        # 版本健康
        versions = (await db.execute(select(RolePackVersion))).scalars().all()
        state_counts = {}
        for v in versions:
            state_counts[v.state] = state_counts.get(v.state, 0) + 1
        return {"total_versions": len(versions), "by_state": state_counts}

    if domain == "knowledge":
        # 知识治理
        total_kc = (await db.execute(select(func.count(KnowledgeCandidate.id)))).scalar() or 0
        approved_kc = (await db.execute(select(func.count(KnowledgeCandidate.id)).where(KnowledgeCandidate.state == "APPROVED"))).scalar() or 0
        pending_kc = (await db.execute(select(func.count(KnowledgeCandidate.id)).where(KnowledgeCandidate.state.in_(["SUBMITTED", "IN_REVIEW"])))).scalar() or 0
        return {
            "total": total_kc, "approved": approved_kc, "pending": pending_kc,
            "approval_rate": round(approved_kc / total_kc * 100, 1) if total_kc > 0 else 0,
        }

    if domain == "security":
        # 安全治理
        deny_count = (await db.execute(select(func.count(AuditLog.id)).where(AuditLog.decision == "DENY"))).scalar() or 0
        allow_count = (await db.execute(select(func.count(AuditLog.id)).where(AuditLog.decision == "ALLOW"))).scalar() or 0
        return {"deny_count": deny_count, "allow_count": allow_count}

    return {"domain": domain, "message": "看板开发中"}
