"""Office_Agent 数据模型层"""
from __future__ import annotations
from datetime import date, datetime
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field


# ─── 枚举 ──────────────────────────────────────

class AgentStatus(str, Enum):
    available = "available"
    indexing = "indexing"
    restricted = "restricted"
    maintenance = "maintenance"

class AgentLifecycle(str, Enum):
    draft = "draft"
    indexing = "indexing"
    pending_check = "pending_check"
    trial = "trial"
    online = "online"

class KnowledgeStatus(str, Enum):
    published = "published"
    expired = "expired"
    pending = "pending"

class TaskStatus(str, Enum):
    in_progress = "in_progress"
    completed = "completed"
    blocked = "blocked"

class SubtaskStatus(str, Enum):
    submitted = "submitted"
    analyzing = "analyzing"
    clarify = "clarify"

class EdgeType(str, Enum):
    verified = "verified"
    inferred = "inferred"


# ─── 基础模型 ──────────────────────────────────

class Department(BaseModel):
    id: str
    name: str
    emoji: str
    description: str
    domains: List[str] = Field(default_factory=list, description="所属领域列表")
    member_count: int = 0
    created_at: datetime = Field(default_factory=datetime.now)

class Domain(BaseModel):
    id: str
    name: str
    department_id: str
    description: str

class Resource(BaseModel):
    id: str
    name: str
    type: str  # service / document / dataset
    description: str
    url: Optional[str] = None

class Agent(BaseModel):
    id: str
    name: str
    emoji: str
    role: str
    department_id: str
    domain_id: str
    status: AgentStatus = AgentStatus.available
    lifecycle: AgentLifecycle = AgentLifecycle.online
    description: str
    resources: List[str] = Field(default_factory=list, description="资源 ID 列表")
    adoption_rate: float = 0.0
    total_sessions: int = 0
    owner: str = ""
    version: str = "v1"
    created_at: datetime = Field(default_factory=datetime.now)

class Knowledge(BaseModel):
    id: str
    title: str
    icon: str = "📘"
    domain_id: str
    department_id: str
    status: KnowledgeStatus = KnowledgeStatus.published
    owner: str
    date: date
    confidence: str  # 高 / 中 / 低
    summary: str
    warning: Optional[str] = None

class Session(BaseModel):
    id: str
    question: str
    assigned_department_id: Optional[str] = None
    assigned_agent_ids: List[str] = Field(default_factory=list)
    status: str = "pending"  # pending / assigned / answered / resolved
    created_at: datetime = Field(default_factory=datetime.now)
    resolved_at: Optional[datetime] = None


# ─── 协作任务模型 ──────────────────────────────

class Subtask(BaseModel):
    id: str
    task_id: str
    agent_id: str
    agent_name: str
    agent_emoji: str
    department_id: str
    domain_name: str
    status: SubtaskStatus = SubtaskStatus.analyzing
    title: str
    detail: Optional[str] = None
    confidence: Optional[str] = None

class Task(BaseModel):
    id: str
    title: str
    description: str
    status: TaskStatus = TaskStatus.in_progress
    meta_dept: str = ""
    meta_tag: str = ""
    meta_time: str = ""
    meta_overtime: str = ""
    subtasks: List[Subtask] = Field(default_factory=list)
    conflict_note: Optional[str] = None
    conflict_type: str = "warning"  # warning / success
    created_at: datetime = Field(default_factory=datetime.now)


# ─── 关系图谱 ──────────────────────────────────

class GraphNode(BaseModel):
    id: str
    label: str
    type: str  # department / domain / agent / resource / knowledge
    verified: bool = True

class GraphEdge(BaseModel):
    source: str
    target: str
    type: EdgeType = EdgeType.verified
    label: str = ""

class GraphData(BaseModel):
    nodes: List[GraphNode] = Field(default_factory=list)
    edges: List[GraphEdge] = Field(default_factory=list)


# ─── KPI / 仪表盘 ──────────────────────────────

class KpiMetric(BaseModel):
    label: str
    value: str
    change: str
    target: str

class DailyStats(BaseModel):
    day: str
    sessions: int
    adopted: int

class DashboardData(BaseModel):
    kpis: List[KpiMetric] = Field(default_factory=list)
    daily_stats: List[DailyStats] = Field(default_factory=list)
    departments: List[Department] = Field(default_factory=list)
    agents: List[Agent] = Field(default_factory=list)

class GraphStats(BaseModel):
    node_count: int
    edge_count: int
    pending_inferred: int


# ─── 请求 / 响应 ───────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str

class LoginResponse(BaseModel):
    token: str
    user_name: str
    role: str

class AskQuestionRequest(BaseModel):
    question: str

class AskQuestionResponse(BaseModel):
    task: Task
    message: str

class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"
