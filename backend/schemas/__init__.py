"""
Pydantic 响应模型
定义 API 返回给前端的数据结构
"""
from pydantic import BaseModel


# ====== 通用 ======
class StandardResponse(BaseModel):
    """统一响应包装"""
    code: int = 0
    message: str = "ok"
    data: any = None


# ====== Dashboard ======
class KPICard(BaseModel):
    """KPI 卡片数据"""
    label: str
    value: str
    change: str
    target: str


class ChartBar(BaseModel):
    """柱状图单组数据"""
    sessions: int
    adopted: int


class DepartmentSummary(BaseModel):
    """部门概要"""
    emoji: str
    name: str
    domains: str
    agent_count: str


class AgentStatus(BaseModel):
    """员工状态一览"""
    emoji: str
    name: str
    title: str
    status: str
    status_label: str
    adoption_rate: int
    session_count: int


class DashboardData(BaseModel):
    """公司总览完整数据"""
    kpis: list[KPICard]
    chart: list[ChartBar]
    departments: list[DepartmentSummary]
    agents: list[AgentStatus]


# ====== Agent ======
class AgentCard(BaseModel):
    """员工办公室卡片"""
    id: str
    name: str
    title: str
    emoji: str
    status: str
    status_label: str
    department: str
    domain: str
    description: str
    resources: list[str]
    tags: list[str]
    adoption_rate: int
    session_count: int


# ====== Collaboration ======
class SubTaskInfo(BaseModel):
    """子任务"""
    agent_name: str
    agent_emoji: str
    department: str
    domain: str
    subtask_title: str
    subtask_detail: str
    status: str
    confidence: str | None


class TaskCardInfo(BaseModel):
    """协作任务卡"""
    id: str
    title: str
    description: str
    state: str
    initiator: str
    deadline_minutes: int
    tags: list[str]
    conflict_note: str | None
    subtasks: list[SubTaskInfo]


# ====== Knowledge ======
class KnowledgeInfo(BaseModel):
    """知识条目"""
    id: str
    title: str
    domain: str
    icon: str
    status: str
    owner: str
    confidence: str
    published_at: str
    conflict_warning: str | None


# ====== Admin ======
class AgentTableRow(BaseModel):
    """员工管理表格行"""
    id: str
    name: str
    title: str
    department: str
    domain: str
    owner: str
    version: int
    status: str
    status_label: str


# ====== Graph ======
class GraphNode(BaseModel):
    id: str
    label: str
    type: str  # department/domain/agent/resource/knowledge
    x: float
    y: float
    verified: bool = True


class GraphEdge(BaseModel):
    source: str
    target: str
    label: str  # 绑定/沉淀/证据/候选
    edge_type: str  # verified/inferred


class GraphData(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    stats: dict
