"""Office_Agent 模拟数据"""
from __future__ import annotations
from datetime import date, datetime
from typing import Optional
from backend.models.models import (
    Department, Domain, Resource, Agent, Knowledge,
    Task, Subtask, GraphData, GraphNode, GraphEdge,
    KpiMetric, DailyStats, DashboardData, GraphStats,
)
from backend.models.models import (
    AgentStatus, AgentLifecycle, KnowledgeStatus,
    TaskStatus, SubtaskStatus, EdgeType,
)


# ─── 部门 ──────────────────────────────────────

departments = [
    Department(id="dept-rd", name="研发部", emoji="💻",
               description="订单域 · 支付域 · 网关域", domains=["订单域", "支付域", "网关域"],
               member_count=3, created_at=datetime(2026, 1, 15)),
    Department(id="dept-pd", name="产品部", emoji="📦",
               description="能力域 · 配置域", domains=["能力域", "配置域"],
               member_count=1, created_at=datetime(2026, 2, 1)),
    Department(id="dept-cs", name="客服部", emoji="🎧",
               description="退款域 · 工单域", domains=["退款域", "工单域"],
               member_count=1, created_at=datetime(2026, 2, 10)),
    Department(id="dept-fa", name="职能部", emoji="📋",
               description="制度域 · 财务域", domains=["制度域", "财务域"],
               member_count=1, created_at=datetime(2026, 3, 1)),
]

# ─── 领域 ──────────────────────────────────────

domains = [
    Domain(id="domain-order", name="订单域", department_id="dept-rd",
           description="订单创建、查询、状态流转"),
    Domain(id="domain-pay", name="支付域", department_id="dept-rd",
           description="支付、退款、对账"),
    Domain(id="domain-gateway", name="网关域", department_id="dept-rd",
           description="路由、鉴权、限流"),
    Domain(id="domain-capability", name="能力域", department_id="dept-pd",
           description="功能能力、适用条件、配置项"),
    Domain(id="domain-refund", name="退款域", department_id="dept-cs",
           description="退款超时、异常处理"),
    Domain(id="domain-regulation", name="制度域", department_id="dept-fa",
           description="报销标准、审批流程、票据合规"),
]

# ─── 资源 ──────────────────────────────────────

resources = [
    Resource(id="res-order-svc", name="order-service", type="service",
             description="订单微服务", url="https://git.internal/order-service"),
    Resource(id="res-order-api", name="订单接口 OpenAPI", type="document",
             description="订单接口规范文档"),
    Resource(id="res-pay-gateway", name="pay-gateway", type="service",
             description="支付网关", url="https://git.internal/pay-gateway"),
    Resource(id="res-pay-risk", name="支付风控数据集", type="dataset",
             description="风控规则与黑名单数据集"),
    Resource(id="res-fiscal-sop", name="财务制度库", type="document",
             description="公司财务相关制度文档"),
    Resource(id="res-cs-sop", name="客服 SOP 知识库", type="document",
             description="客服标准操作流程"),
    Resource(id="res-api-gateway", name="api-gateway", type="service",
             description="网关服务", url="https://git.internal/api-gateway"),
    Resource(id="res-capability-list", name="产品能力清单", type="document",
             description="产品功能能力清单文档"),
]

# ─── 员工 ──────────────────────────────────────

agents = [
    Agent(id="agent-lin", name="林向阳", emoji="🧑‍💻", role="订单域研发员工",
          department_id="dept-rd", domain_id="domain-order",
          description="订单创建、查询、状态流转相关接口的发现与调用指导",
          resources=["res-order-svc", "res-order-api"],
          adoption_rate=0.72, total_sessions=1284,
          owner="张磊", version="v3",
          status=AgentStatus.available, lifecycle=AgentLifecycle.online),
    Agent(id="agent-su", name="苏晚", emoji="👩‍💻", role="支付域研发员工",
          department_id="dept-rd", domain_id="domain-pay",
          description="支付、退款、对账接口的调用链路与幂等处理指导",
          resources=["res-pay-gateway", "res-pay-risk"],
          adoption_rate=0.68, total_sessions=903,
          owner="陈昊", version="v2",
          status=AgentStatus.indexing, lifecycle=AgentLifecycle.indexing),
    Agent(id="agent-zhou", name="周知", emoji="🧑‍⚖️", role="报销制度员工",
          department_id="dept-fa", domain_id="domain-regulation",
          description="报销标准、审批流程、票据合规的制度问答",
          resources=["res-fiscal-sop"],
          adoption_rate=0.81, total_sessions=656,
          owner="李芳", version="v2",
          status=AgentStatus.available, lifecycle=AgentLifecycle.online),
    Agent(id="agent-he", name="何鲤", emoji="🧑‍🔧", role="退款流程员工",
          department_id="dept-cs", domain_id="domain-refund",
          description="退款超时、异常码处理与标准话术",
          resources=["res-cs-sop"],
          adoption_rate=0.76, total_sessions=1120,
          owner="王敏", version="v1",
          status=AgentStatus.available, lifecycle=AgentLifecycle.trial),
    Agent(id="agent-zheng", name="郑帆", emoji="🧑‍🏫", role="能力域产品员工",
          department_id="dept-pd", domain_id="domain-capability",
          description="功能能力、适用条件、配置项与异常说明",
          resources=["res-capability-list"],
          adoption_rate=0.64, total_sessions=402,
          owner="刘洋", version="v1",
          status=AgentStatus.restricted, lifecycle=AgentLifecycle.pending_check),
    Agent(id="agent-xu", name="许安", emoji="🧑‍🚀", role="网关域研发员工",
          department_id="dept-rd", domain_id="domain-gateway",
          description="路由、鉴权、限流配置与网关链路问答",
          resources=["res-api-gateway"],
          adoption_rate=0.70, total_sessions=288,
          owner="张磊", version="v1",
          status=AgentStatus.maintenance, lifecycle=AgentLifecycle.trial),
]

# ─── 知识库 ────────────────────────────────────

knowledge_entries = [
    Knowledge(id="kn-001", title="创建订单推荐接口与幂等处理", icon="📘",
              domain_id="domain-order", department_id="dept-rd",
              status=KnowledgeStatus.published, owner="张磊",
              date=date(2026, 7, 14), confidence="高",
              summary="订单创建推荐接口与幂等键处理最佳实践"),
    Knowledge(id="kn-002", title="退款超时标准处理流程与话术", icon="📕",
              domain_id="domain-refund", department_id="dept-cs",
              status=KnowledgeStatus.published, owner="王敏",
              date=date(2026, 7, 11), confidence="高",
              summary="退款超时时的标准处理流程与客服话术"),
    Knowledge(id="kn-003", title="差旅报销标准与审批流程 v8", icon="📗",
              domain_id="domain-regulation", department_id="dept-fa",
              status=KnowledgeStatus.published, owner="李芳",
              date=date(2026, 7, 1), confidence="高",
              summary="差旅报销标准、审批流程与票据合规要求"),
    Knowledge(id="kn-004", title="支付回调幂等键设计说明", icon="📙",
              domain_id="domain-pay", department_id="dept-rd",
              status=KnowledgeStatus.expired, owner="陈昊",
              date=date(2026, 5, 20), confidence="中",
              summary="支付回调幂等键设计原理与实现",
              warning="内容可能与最新资源冲突，检索中已降权，建议 Owner 复核"),
    Knowledge(id="kn-005", title="分账能力适用条件与限制", icon="📓",
              domain_id="domain-capability", department_id="dept-pd",
              status=KnowledgeStatus.pending, owner="刘洋",
              date=date(2026, 7, 15), confidence="中",
              summary="分账功能的适用条件、限制与配置说明"),
]

# ─── 协作任务 ──────────────────────────────────

subtasks_task1 = [
    Subtask(id="sub-1", task_id="task-1", agent_id="agent-su",
            agent_name="苏晚", agent_emoji="👩‍💻",
            department_id="dept-rd", domain_name="支付域",
            status=SubtaskStatus.submitted,
            title="支付网关回调与幂等键核对",
            detail="回调签名校验通过，幂等键命中重复，疑似上游重试",
            confidence="高"),
    Subtask(id="sub-2", task_id="task-1", agent_id="agent-xu",
            agent_name="许安", agent_emoji="🧑‍🚀",
            department_id="dept-rd", domain_name="网关域",
            status=SubtaskStatus.analyzing,
            title="网关路由与限流是否触发"),
    Subtask(id="sub-3", task_id="task-1", agent_id="agent-lin",
            agent_name="林向阳", agent_emoji="🧑‍💻",
            department_id="dept-rd", domain_name="订单域",
            status=SubtaskStatus.clarify,
            title="订单状态机是否阻塞支付创建",
            detail="需确认订单是否处于 CLOSED 状态"),
]

subtasks_task2 = [
    Subtask(id="sub-4", task_id="task-2", agent_id="agent-zheng",
            agent_name="郑帆", agent_emoji="🧑‍🏫",
            department_id="dept-pd", domain_name="能力域",
            status=SubtaskStatus.submitted,
            title="分账适用条件与限制（产品）",
            detail="仅支持担保交易，单笔最多 10 个分账方",
            confidence="高"),
    Subtask(id="sub-5", task_id="task-2", agent_id="agent-su",
            agent_name="苏晚", agent_emoji="👩‍💻",
            department_id="dept-rd", domain_name="支付域",
            status=SubtaskStatus.submitted,
            title="分账接口与幂等实现（研发）",
            detail="接口已就绪，灰度开关 split.enable 控制",
            confidence="中"),
]

tasks = [
    Task(id="task-1", title="支付失败涉及哪些系统？先查什么？",
         description="定位支付失败的跨系统链路与排查顺序",
         status=TaskStatus.in_progress,
         meta_dept="部门对接人（研发部）",
         meta_tag="release/2.14 · 2026-07-16",
         meta_overtime="超时 30 分钟",
         subtasks=subtasks_task1,
         conflict_note="冲突待决：支付域认为是上游重试，网关域尚未确认限流数据——待网关域提交后再判定。",
         conflict_type="warning"),
    Task(id="task-2", title="分账能力上线的规则与技术约束",
         description="汇总产品规则与研发实现的一致性",
         status=TaskStatus.completed,
         meta_dept="用户主动发起", meta_tag="2026-07-15",
         meta_overtime="超时 45 分钟",
         subtasks=subtasks_task2,
         conflict_note="汇总结论：分账当前仅对担保交易开放，单笔 ≤10 分账方，由灰度开关控制；文档与代码口径一致，建议沉淀为知识条目。",
         conflict_type="success"),
]

# ─── 关系图谱 ──────────────────────────────────

def build_graph() -> GraphData:
    nodes = [
        GraphNode(id="dept-rd", label="研发部", type="department"),
        GraphNode(id="domain-order", label="订单域", type="domain"),
        GraphNode(id="domain-pay", label="支付域", type="domain"),
        GraphNode(id="agent-lin", label="林向阳", type="agent", verified=True),
        GraphNode(id="agent-su", label="苏晚", type="agent", verified=True),
        GraphNode(id="res-order-svc", label="order-service", type="resource", verified=True),
        GraphNode(id="res-pay-gateway", label="pay-gateway", type="resource", verified=True),
        GraphNode(id="kn-001", label="订单幂等知识", type="knowledge", verified=True),
        GraphNode(id="kn-004", label="支付回调知识", type="knowledge", verified=False),
    ]
    edges = [
        GraphEdge(source="dept-rd", target="domain-order", label="绑定"),
        GraphEdge(source="dept-rd", target="domain-pay", label="绑定"),
        GraphEdge(source="domain-order", target="agent-lin", label="沉淀"),
        GraphEdge(source="domain-pay", target="agent-su", label="沉淀"),
        GraphEdge(source="agent-lin", target="res-order-svc", label="证据"),
        GraphEdge(source="agent-su", target="res-pay-gateway", label="证据"),
        GraphEdge(source="agent-lin", target="kn-001", label="证据"),
        GraphEdge(source="agent-su", target="kn-004", label="候选", type=EdgeType.inferred),
        GraphEdge(source="domain-pay", target="kn-004", label="推断", type=EdgeType.inferred),
    ]
    return GraphData(nodes=nodes, edges=edges)


# ─── KPI / 仪表盘 ──────────────────────────────

kpis = [
    KpiMetric(label="答案采纳率", value="72%", change="↑ +4%", target="目标 ≥ 60%"),
    KpiMetric(label="证据覆盖率", value="96%", change="↑ +1%", target="目标 ≥ 95%"),
    KpiMetric(label="部门分诊准确率", value="87%", change="↑ +2%", target="目标 ≥ 85%"),
    KpiMetric(label="满意度", value="4.3", change="↑ +0.1", target="目标 ≥ 4.2"),
]

daily_stats = [
    DailyStats(day="周一", sessions=320, adopted=240),
    DailyStats(day="周二", sessions=375, adopted=280),
    DailyStats(day="周三", sessions=360, adopted=260),
    DailyStats(day="周四", sessions=468, adopted=334),
    DailyStats(day="周五", sessions=600, adopted=434),
    DailyStats(day="周六", sessions=268, adopted=200),
    DailyStats(day="周日", sessions=200, adopted=154),
]

graph_stats = GraphStats(
    node_count=9, edge_count=10, pending_inferred=1
)


# ─── 聚合方法 ──────────────────────────────────

def get_dashboard() -> DashboardData:
    return DashboardData(
        kpis=kpis,
        daily_stats=daily_stats,
        departments=departments,
        agents=[a for a in agents if a.status != AgentStatus.maintenance],
    )

def get_agents_by_department(dept_id: Optional[str] = None) -> list:
    if dept_id:
        return [a for a in agents if a.department_id == dept_id]
    return agents

def get_knowledge_by_department(dept_id: Optional[str] = None) -> list:
    if dept_id:
        return [k for k in knowledge_entries if k.department_id == dept_id]
    return knowledge_entries

def get_tasks_by_status(status: Optional[str] = None) -> list:
    if status:
        return [t for t in tasks if t.status.value == status]
    return tasks

def resolve_department_name(dept_id: str) -> str:
    for d in departments:
        if d.id == dept_id:
            return d.name
    return dept_id

def resolve_agent_name(agent_id: str) -> str:
    for a in agents:
        if a.id == agent_id:
            return a.name
    return agent_id
