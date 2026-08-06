"""
知识与案例路由
从 MySQL 读取知识候选条目
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select

from backend.database import get_db
from backend.models.knowledge import KnowledgeCandidate

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

# 状态映射：数据库 status → API status（兼容旧前端 pending_review→pending）
_STATUS_API_MAP = {
    "published": "published",
    "expired": "expired",
    "pending_review": "pending",
}


@router.get("")
async def list_knowledge(
    department_id: Optional[str] = Query(None, alias="departmentId"),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db = Depends(get_db),
):
    """获取知识条目列表，支持按部门/状态/关键词筛选"""
    query = select(KnowledgeCandidate)

    if department_id:
        query = query.where(KnowledgeCandidate.department.contains(department_id))
    if status:
        # API 的 "pending" 映射到数据库的 "pending_review"
        db_status = "pending_review" if status == "pending" else status
        query = query.where(KnowledgeCandidate.status == db_status)
    if search:
        query = query.where(KnowledgeCandidate.title.contains(search))

    query = query.order_by(KnowledgeCandidate.created_at.desc())
    result = await db.execute(query)
    entries = result.scalars().all()

    return [_knowledge_to_dict(k) for k in entries]


@router.get("/{knowledge_id}")
async def get_knowledge(knowledge_id: str, db = Depends(get_db)):
    """获取单个知识条目详情"""
    result = await db.execute(
        select(KnowledgeCandidate).where(KnowledgeCandidate.id == knowledge_id)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="知识条目不存在")
    return _knowledge_to_dict(entry)


def _knowledge_to_dict(k: KnowledgeCandidate) -> dict:
    """将 KnowledgeCandidate ORM 转为 API 响应"""
    return {
        "id": k.id,
        "title": k.title,
        "icon": k.icon,
        "domain_id": k.domain or "",
        "department_id": k.department or "",
        "status": _STATUS_API_MAP.get(k.status, k.status),
        "owner": k.owner or "",
        "date": k.published_at or "",
        "confidence": "高" if k.confidence == "HIGH" else ("中" if k.confidence == "MEDIUM" else "低"),
        "summary": k.title,
        "warning": k.conflict_warning,
    }
