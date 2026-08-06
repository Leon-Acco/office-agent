"""
员工 / Agent 管理路由
从 MySQL 读取员工数据，支持按部门/状态筛选
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.agent import Agent
from backend.models.company import Department, Domain

router = APIRouter(prefix="/api/agents", tags=["agents"])

# 状态映射：数据库 lifecycle → API status
_STATUS_MAP = {
    "online": "available",
    "indexing": "indexing",
    "trial": "available",
    "pending_check": "restricted",
    "maintenance": "maintenance",
}


def _agent_to_dict(a: Agent, dept_name: str = "", domain_name: str = "") -> dict:
    """将 Agent ORM 对象转为 API 响应字典"""
    return {
        "id": a.id,
        "name": a.name,
        "emoji": a.emoji,
        "role": a.title,
        "department_id": dept_name,
        "domain_id": domain_name,
        "status": _STATUS_MAP.get(a.status, "available"),
        "description": a.description,
        "resources": a.resources or [],
        "adoption_rate": a.adoption_rate / 100,
        "total_sessions": a.session_count,
        "owner": a.owner,
        "version": f"v{a.version}",
    }


async def _build_name_maps(db: AsyncSession) -> tuple[dict, dict]:
    """构建部门/领域 ID→名称映射"""
    depts = (await db.execute(select(Department))).scalars().all()
    domains = (await db.execute(select(Domain))).scalars().all()
    return (
        {d.id: d.name for d in depts},
        {d.id: d.name for d in domains},
    )


@router.get("")
async def list_agents(
    department_id: Optional[str] = Query(None, alias="departmentId"),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """获取员工列表，可按部门或状态筛选"""
    query = select(Agent)
    if department_id:
        query = query.where(Agent.department_id == department_id)
    if status:
        # 将 API 状态映射回数据库状态
        reverse_map = {}
        for db_st, api_st in _STATUS_MAP.items():
            reverse_map.setdefault(api_st, []).append(db_st)
        db_statuses = reverse_map.get(status, [status])
        query = query.where(Agent.status.in_(db_statuses))

    result = await db.execute(query)
    agents = result.scalars().all()

    dept_names, domain_names = await _build_name_maps(db)
    return [_agent_to_dict(a, dept_names.get(a.department_id, ""), domain_names.get(a.domain_id, "")) for a in agents]


@router.get("/{agent_id}")
async def get_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    """获取单个员工详情"""
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="员工不存在")

    dept_names, domain_names = await _build_name_maps(db)
    return _agent_to_dict(agent, dept_names.get(agent.department_id, ""), domain_names.get(agent.domain_id, ""))


@router.get("/{agent_id}/resources")
async def get_agent_resources(agent_id: str, db: AsyncSession = Depends(get_db)):
    """获取员工关联的资源（从 JSON 字段返回）"""
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="员工不存在")

    # resources 字段存储的是展示用的资源描述列表
    # 如 ["💻 order-service", "📄 订单接口 OpenAPI"]
    resources = agent.resources or []
    output = []
    for r in resources:
        parts = r.split(" ", 1)
        icon = parts[0] if len(parts) > 1 else "📄"
        name = parts[1] if len(parts) > 1 else r
        rtype = "service" if "💻" in icon else "document"
        output.append({"id": r, "name": name, "type": rtype, "description": name})
    return output
