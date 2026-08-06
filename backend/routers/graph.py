"""
关系图谱路由
从 MySQL 动态构建组织与资源关系图:
部门 → 领域 → 员工 → 仓库(AgentRepoBinding)/ Skill / MCP 工具(岗位包白名单)
知识库条目按「领域约定 + 作者」双连边
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.company import Department, Domain
from backend.models.agent import Agent, RolePack
from backend.models.governance import Repository, AgentRepoBinding
from backend.models.resource import Skill, Tool
from backend.models.knowledge import KnowledgeCandidate

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.get("")
async def get_graph(db: AsyncSession = Depends(get_db)):
    """获取完整图谱数据:部门→领域→员工→仓库/能力/工具/知识"""
    # 批量查询,避免 N+1
    depts = (await db.execute(select(Department))).scalars().all()
    domains = (await db.execute(select(Domain))).scalars().all()
    agents = (await db.execute(select(Agent))).scalars().all()
    role_packs = (await db.execute(select(RolePack))).scalars().all()
    repos = (await db.execute(select(Repository))).scalars().all()
    bindings = (await db.execute(select(AgentRepoBinding))).scalars().all()
    skills = (await db.execute(select(Skill))).scalars().all()
    tools = (await db.execute(select(Tool))).scalars().all()
    knowledges = (await db.execute(
        select(KnowledgeCandidate).where(KnowledgeCandidate.state != "REJECTED")
    )).scalars().all()

    nodes: list[dict] = []
    edges: list[dict] = []
    node_ids: set[str] = set()

    def add_node(nid: str, label: str, ntype: str, verified: bool = True):
        """按 id 去重加节点(共享资源单节点多边)"""
        if nid in node_ids:
            return
        node_ids.add(nid)
        nodes.append({"id": nid, "label": label, "type": ntype, "verified": verified})

    # 部门节点
    for d in depts:
        add_node(d.id, d.name, "department")

    # 领域节点 + 部门→领域边
    for dm in domains:
        add_node(dm.id, dm.name, "domain")
        edges.append({"source": dm.department_id, "target": dm.id, "label": "绑定", "type": "verified"})

    # 索引表
    rp_map = {rp.id: rp for rp in role_packs}
    repo_map = {r.id: r for r in repos}
    agent_repo_ids: dict[str, list[str]] = {}
    for b in bindings:
        agent_repo_ids.setdefault(b.agent_id, []).append(b.repo_id)

    # skill_key / name 双兼容索引(同 build_context 的历史兼容策略)
    skill_by_key = {s.skill_key: s for s in skills if s.skill_key}
    skill_by_name = {s.name: s for s in skills}
    tool_by_key = {t.tool_key: t for t in tools if t.tool_key}
    tool_by_name = {t.name: t for t in tools}

    # 员工节点 + 领域→员工边 + 员工资源绑定边
    for a in agents:
        verified = a.status in ("online", "indexing", "trial")
        add_node(a.id, a.name, "agent", verified)
        edges.append({"source": a.domain_id, "target": a.id, "label": "沉淀", "type": "verified"})

        spec = (rp_map.get(a.role_pack_id).config or {}) if a.role_pack_id in rp_map else {}

        # 员工→仓库(AgentRepoBinding)
        for rid in agent_repo_ids.get(a.id, []):
            repo = repo_map.get(rid)
            if not repo:
                continue
            nid = f"repo-{repo.id}"
            add_node(nid, repo.name, "repo", repo.state == "READY")
            edges.append({"source": a.id, "target": nid, "label": "绑定", "type": "verified"})

        # 员工→Skill(直绑优先,回退岗位包 skills)
        for sk in (a.skills or spec.get("skills", [])):
            s = skill_by_key.get(sk) or skill_by_name.get(sk)
            if not s:
                continue
            nid = f"skill-{s.id}"
            add_node(nid, s.name, "skill", s.state == "RELEASED")
            edges.append({"source": a.id, "target": nid, "label": "具备", "type": "verified"})

        # 员工→MCP 工具(岗位包白名单)
        for tk in spec.get("tools", []):
            t = tool_by_key.get(tk) or tool_by_name.get(tk)
            if not t:
                continue
            nid = f"tool-{t.id}"
            add_node(nid, t.name, "tool", t.state == "APPROVED")
            edges.append({"source": a.id, "target": nid, "label": "调用", "type": "verified"})

    # 知识节点 + 领域/作者双连边
    agent_by_name = {a.name: a for a in agents}
    for k in knowledges:
        nid = f"kn-{k.id}"
        add_node(nid, k.title, "knowledge", k.state == "APPROVED" or k.status == "published")
        # 知识→领域:domain 字段与领域名双向包含(沿用知识检索约定)
        for dm in domains:
            if k.domain and dm.name and (k.domain in dm.name or dm.name in k.domain):
                edges.append({"source": nid, "target": dm.id, "label": "归属", "type": "verified"})
                break
        # 知识→作者员工
        author = agent_by_name.get(k.owner or "")
        if author:
            edges.append({"source": nid, "target": author.id, "label": "撰写", "type": "verified"})

    return {"nodes": nodes, "edges": edges}


@router.get("/stats")
async def get_graph_stats(db: AsyncSession = Depends(get_db)):
    """获取图谱统计数据"""
    graph = await get_graph(db)
    inferred_count = sum(1 for e in graph["edges"] if e.get("type") == "inferred")
    return {
        "node_count": len(graph["nodes"]),
        "edge_count": len(graph["edges"]),
        "pending_inferred": inferred_count,
    }
