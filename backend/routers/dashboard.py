"""
公司总览看板 API
所有指标从 MySQL 实时聚合，无硬编码假数据
"""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.company import Department, Domain
from backend.models.agent import Agent
from backend.models.session import Session, Message
from backend.models.knowledge import KnowledgeCandidate
from backend.models.task import TaskCard
from backend.models.governance import Repository
from backend.models.resource import Skill, Tool, Resource

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard")
async def get_dashboard(db: AsyncSession = Depends(get_db)):
    """返回公司总览看板完整数据（全部从数据库聚合）"""

    # === 1. KPI 从数据库聚合 ===
    # 员工总数 & 可用员工数
    total_agents = (await db.execute(select(func.count(Agent.id)))).scalar() or 0
    online_agents = (await db.execute(
        select(func.count(Agent.id)).where(Agent.status.in_(["online", "trial"]))
    )).scalar() or 0

    # 平均采纳率（真实数据源：用户对回答的点赞/点踩，up/(up+down)）
    fb_rows = (await db.execute(
        select(Message.feedback, func.count(Message.id))
        .where(Message.role == "assistant", Message.feedback != "")
        .group_by(Message.feedback)
    )).all()
    fb_map = {r[0]: r[1] for r in fb_rows}
    fb_up, fb_down = fb_map.get("up", 0), fb_map.get("down", 0)
    fb_total = fb_up + fb_down
    adoption_value = round(fb_up / fb_total * 100) if fb_total else None  # 无反馈时 None → 前端显示 —

    # 总会话数（真实 Session 表计数，不再用 Agent.session_count 冗余字段）
    total_sessions = (await db.execute(
        select(func.count(Session.id))
    )).scalar() or 0

    # 回答总数
    total_answers = (await db.execute(
        select(func.count(Message.id)).where(Message.role == "assistant")
    )).scalar() or 0

    # 知识资产数 = 已发布知识条目 + 资源中心文档(两类知识载体合并计数,
    # 用户视角上传文档即知识资产;卡片 label 仍叫「已发布知识」)
    knowledge_count = (await db.execute(
        select(func.count(KnowledgeCandidate.id)).where(
            KnowledgeCandidate.status == "published"
        )
    )).scalar() or 0
    doc_count = (await db.execute(
        select(func.count(Resource.id)).where(Resource.type == "document")
    )).scalar() or 0
    knowledge_count += doc_count

    # 协作任务数
    task_count = (await db.execute(
        select(func.count(TaskCard.id))
    )).scalar() or 0

    # 代码库 / Skill / MCP 工具数量
    repo_count = (await db.execute(select(func.count(Repository.id)))).scalar() or 0
    skill_count = (await db.execute(select(func.count(Skill.id)))).scalar() or 0
    mcp_count = (await db.execute(
        select(func.count(Tool.id)).where(Tool.type == "mcp")
    )).scalar() or 0
    # 内置工具数（build_tool_registry 注册的业务 4 + 代码 6，与 frontdesk 总台白名单一致）
    builtin_count = 10

    # 构建 KPI（真实数据 + icon 由后端下发，前端不再硬编码图标数组）
    kpis = [
        {
            "label": "可用员工",
            "value": str(online_agents),
            "change": f"共 {total_agents} 名",
            "target": f"在线率 {round(online_agents/total_agents*100) if total_agents else 0}%",
            "icon": "groups",
        },
        {
            "label": "总会话数",
            "value": str(total_sessions),
            "change": f"回答 {total_answers} 条",
            "target": "全员服务量",
            "icon": "forum",
        },
        {
            "label": "平均采纳率",
            "value": f"{adoption_value}%" if adoption_value is not None else "—",
            "change": f"点赞 {fb_up} / 点踩 {fb_down}" if fb_total else "暂无评价数据",
            "target": "目标 ≥ 60%",
            "icon": "verified",
        },
        {
            "label": "已发布知识",
            "value": str(knowledge_count),
            "change": f"协作任务 {task_count}",
            "target": "知识沉淀闭环",
            "icon": "account_tree",
        },
        {
            "label": "代码库",
            "value": str(repo_count),
            "change": "已接入仓库",
            "target": "代码检索底座",
            "icon": "folder_code",
        },
        {
            "label": "Skill",
            "value": str(skill_count),
            "change": "已发布技能",
            "target": "能力复用",
            "icon": "extension",
        },
        {
            "label": "MCP 工具",
            "value": str(mcp_count),
            "change": "外部服务接入",
            "target": "开放生态",
            "icon": "cable",
        },
        {
            "label": "内置工具",
            "value": str(builtin_count),
            "change": "业务 4 + 代码 6",
            "target": "开箱即用",
            "icon": "build",
        },
    ]

    # === 2. 图表数据：按天聚合最近 7 天的会话数与回答数（均为真实统计）===
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    recent_sessions = (await db.execute(
        select(
            func.date(Session.created_at).label("dt"),
            func.count(Session.id).label("cnt"),
        ).where(Session.created_at >= seven_days_ago).group_by("dt").order_by("dt")
    )).all()
    # 回答数：按天聚合 assistant 消息数（采纳率无按天数据源，不用假数据）
    recent_answers = (await db.execute(
        select(
            func.date(Message.created_at).label("dt"),
            func.count(Message.id).label("cnt"),
        ).where(Message.created_at >= seven_days_ago, Message.role == "assistant")
        .group_by("dt")
    )).all()
    answer_map = {str(r.dt): r.cnt for r in recent_answers}

    if recent_sessions and len(recent_sessions) > 0:
        daily_stats = [
            {"day": str(row.dt), "sessions": row.cnt, "answered": answer_map.get(str(row.dt), 0)}
            for row in recent_sessions
        ]
    else:
        # 数据库无会话记录 → 返回空（前端显示"暂无数据"）
        daily_stats = []

    # === 3. 部门列表 ===
    depts = (await db.execute(select(Department))).scalars().all()
    all_domains = (await db.execute(select(Domain))).scalars().all()

    departments = []
    for dept in depts:
        dept_domains = [d for d in all_domains if d.department_id == dept.id]
        domain_names = " · ".join(d.name for d in dept_domains)
        member_count = (await db.execute(
            select(func.count(Agent.id)).where(Agent.department_id == dept.id)
        )).scalar() or 0

        departments.append({
            "id": dept.id,
            "name": dept.name,
            "emoji": dept.emoji,
            "description": domain_names,
            "domains": [d.name for d in dept_domains],
            "member_count": member_count,
        })

    # === 4. 员工状态一览 ===
    agents = (await db.execute(select(Agent))).scalars().all()
    dept_names = {d.id: d.name for d in depts}
    domain_names_map = {d.id: d.name for d in all_domains}

    # 员工级真实统计（避免 N+1，两次聚合查询）:
    # 1) 每个员工收到的点赞/点踩数 → 采纳率
    agent_fb_rows = (await db.execute(
        select(Message.agent_id, Message.feedback, func.count(Message.id))
        .where(Message.role == "assistant", Message.feedback != "", Message.agent_id.isnot(None))
        .group_by(Message.agent_id, Message.feedback)
    )).all()
    agent_fb: dict[str, dict[str, int]] = {}
    for aid, fb, cnt in agent_fb_rows:
        agent_fb.setdefault(aid, {})[fb] = cnt

    # 2) 每个员工的回答数 → 服务量
    agent_msg_rows = (await db.execute(
        select(Message.agent_id, func.count(Message.id))
        .where(Message.role == "assistant", Message.agent_id.isnot(None))
        .group_by(Message.agent_id)
    )).all()
    agent_answers = dict(agent_msg_rows)

    # 状态原样透传，由前端统一维护样式映射（避免前后端两套键对不上）
    # adoption_rate 无评价数据时为 None → 前端显示 —
    agent_list = []
    for a in agents:
        fb = agent_fb.get(a.id, {})
        up, down = fb.get("up", 0), fb.get("down", 0)
        total = up + down
        agent_list.append({
            "id": a.id,
            "name": a.name,
            "emoji": a.emoji,
            "role": a.title,
            "department": dept_names.get(a.department_id, ""),
            "domain": domain_names_map.get(a.domain_id, ""),
            "status": a.status or "online",
            "adoption_rate": round(up / total * 100) / 100 if total else None,
            "total_sessions": agent_answers.get(a.id, 0),
            "owner": a.owner,
            "version": f"v{a.version}",
        })

    return {
        "kpis": kpis,
        "daily_stats": daily_stats,
        "departments": departments,
        "agents": agent_list,
    }


@router.get("/departments")
async def list_departments(db: AsyncSession = Depends(get_db)):
    """获取部门列表"""
    depts = (await db.execute(select(Department))).scalars().all()
    return [
        {"id": d.id, "name": d.name, "emoji": d.emoji, "description": d.description}
        for d in depts
    ]
