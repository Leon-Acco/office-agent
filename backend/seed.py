"""
Mock 数据填充脚本
数据完全对齐 Figma 设计稿中的示例
"""
import asyncio
from sqlalchemy import select

from backend.database import engine, async_session, Base
from backend.models.company import Company, Department, Domain
from backend.models.agent import Agent, RolePack
from backend.models.session import Session
from backend.models.task import TaskCard, TaskAssignment
from backend.models.knowledge import KnowledgeCandidate
from backend.models.evidence import Evidence


async def seed_mock_data():
    """填充全部 Mock 数据（幂等：已有数据则跳过）"""
    async with async_session() as session:
        # 幂等检查
        existing = await session.scalar(select(Company).limit(1))
        if existing:
            return

        # === 1. 公司 ===
        company = Company(
            name="Agent 办公室",
            description="一家全部由 AI 员工组成的虚拟公司",
        )
        session.add(company)
        await session.flush()

        # === 2. 部门 + 领域 ===
        departments_data = [
            ("研发部", "💻", ["订单域", "支付域", "网关域"]),
            ("产品部", "📦", ["能力域", "配置域"]),
            ("客服部", "🎧", ["退款域", "工单域"]),
            ("职能部", "📋", ["制度域", "财务域"]),
        ]
        dept_map = {}
        domain_map = {}
        for dept_name, emoji, domains in departments_data:
            dept = Department(
                company_id=company.id,
                name=dept_name,
                emoji=emoji,
                description=f"{dept_name}——{dept_name}相关领域",
            )
            session.add(dept)
            await session.flush()
            dept_map[dept_name] = dept
            for dm_name in domains:
                dm = Domain(
                    department_id=dept.id,
                    name=dm_name,
                )
                session.add(dm)
                await session.flush()
                domain_map[dm_name] = dm

        # === 3. 员工（6 名，对齐 Figma）===
        agents_data = [
            ("林向阳", "订单域研发员工", "🧑‍💻", "研发部", "订单域",
             "online", 3, "张磊", "订单创建、查询、状态流转相关接口的发现与调用指导",
             ["💻 order-service", "📄 订单接口 OpenAPI"], 72, 1284),
            ("苏晚", "支付域研发员工", "👩‍💻", "研发部", "支付域",
             "indexing", 2, "陈昊", "支付、退款、对账接口的调用链路与幂等处理指导",
             ["💻 pay-gateway", "🗄️ 支付风控数据集"], 68, 903),
            ("周知", "报销制度员工", "🧑‍⚖️", "职能部", "制度域",
             "online", 2, "李芳", "报销标准、审批流程、票据合规的制度问答",
             ["📄 财务制度库"], 81, 656),
            ("何鲤", "退款流程员工", "🧑‍🔧", "客服部", "退款域",
             "trial", 1, "王敏", "退款超时、异常码处理与标准话术",
             ["📄 客服 SOP 知识库"], 76, 1120),
            ("郑帆", "能力域产品员工", "🧑‍🏫", "产品部", "能力域",
             "pending_check", 1, "刘洋", "功能能力、适用条件、配置项与异常说明",
             ["📄 产品能力清单"], 64, 402),
            ("许安", "网关域研发员工", "🧑‍🚀", "研发部", "网关域",
             "maintenance", 1, "", "路由、鉴权、限流配置与网关链路问答",
             ["💻 api-gateway"], 70, 288),
        ]
        for (name, title, emoji, dept_name, domain_name,
             status, ver, owner, desc, resources, adopt_rate, sess_count) in agents_data:
            agent = Agent(
                name=name,
                title=title,
                emoji=emoji,
                department_id=dept_map[dept_name].id,
                domain_id=domain_map[domain_name].id,
                status=status,
                version=ver,
                owner=owner,
                description=desc,
                resources=resources,
                tags=[dept_name, domain_name],
                adoption_rate=adopt_rate,
                session_count=sess_count,
            )
            session.add(agent)

        await session.flush()

        # === 4. 协作任务卡（2 个，对齐 Figma）===
        # 任务 1 — 进行中
        task1 = TaskCard(
            title="支付失败涉及哪些系统？先查什么？",
            description="定位支付失败的跨系统链路与排查顺序",
            state="in_progress",
            initiator="部门对接人（研发部）",
            deadline_minutes=30,
            tags=["release/2.14", "2026-07-16"],
            conflict_note="⚠️ 冲突待决：支付域认为是上游重试，网关域尚未确认限流数据——待网关域提交后再判定。",
        )
        session.add(task1)
        await session.flush()

        # 子任务（3 名员工并行）
        subtasks1 = [
            ("苏晚", "👩‍💻", "研发部", "支付域", "支付网关回调与幂等键核对",
             "回调签名校验通过，幂等键命中重复，疑似上游重试", "submitted", "HIGH"),
            ("许安", "🧑‍🚀", "研发部", "网关域", "网关路由与限流是否触发",
             "", "analyzing", None),
            ("林向阳", "🧑‍💻", "研发部", "订单域", "订单状态机是否阻塞支付创建",
             "需确认订单是否处于 CLOSED 状态", "clarify", None),
        ]
        # 查 agent id
        all_agents = {a.name: a for a in (await session.scalars(select(Agent))).all()}
        for (agent_name, emoji, dept, domain, sub_title, sub_detail, sub_status, conf) in subtasks1:
            a = all_agents.get(agent_name)
            assignment = TaskAssignment(
                task_card_id=task1.id,
                agent_id=a.id if a else "",
                agent_name=agent_name,
                agent_emoji=emoji,
                department=dept,
                domain=domain,
                subtask_title=sub_title,
                subtask_detail=sub_detail,
                status=sub_status,
                confidence=conf,
            )
            session.add(assignment)

        # 任务 2 — 已完成
        task2 = TaskCard(
            title="分账能力上线的规则与技术约束",
            description="汇总产品规则与研发实现的一致性",
            state="completed",
            initiator="用户主动发起",
            deadline_minutes=45,
            tags=["2026-07-15"],
            conflict_note="✅ 汇总结论：分账当前仅对担保交易开放，单笔 ≤10 分账方，由灰度开关控制；文档与代码口径一致，建议沉淀为知识条目。",
        )
        session.add(task2)
        await session.flush()

        subtasks2 = [
            ("郑帆", "🧑‍🏫", "产品部", "能力域", "分账适用条件与限制（产品）",
             "仅支持担保交易，单笔最多 10 个分账方", "submitted", "HIGH"),
            ("苏晚", "👩‍💻", "研发部", "支付域", "分账接口与幂等实现（研发）",
             "接口已就绪，灰度开关 split.enable 控制", "submitted", "MEDIUM"),
        ]
        for (agent_name, emoji, dept, domain, sub_title, sub_detail, sub_status, conf) in subtasks2:
            a = all_agents.get(agent_name)
            assignment = TaskAssignment(
                task_card_id=task2.id,
                agent_id=a.id if a else "",
                agent_name=agent_name,
                agent_emoji=emoji,
                department=dept,
                domain=domain,
                subtask_title=sub_title,
                subtask_detail=sub_detail,
                status=sub_status,
                confidence=conf,
            )
            session.add(assignment)

        # === 5. 知识条目（5 条，对齐 Figma）===
        knowledge_data = [
            ("创建订单推荐接口与幂等处理", "订单域 · 研发", "📘", "published", "张磊", "HIGH", "2026-07-14", None),
            ("退款超时标准处理流程与话术", "退款域 · 客服", "📕", "published", "王敏", "HIGH", "2026-07-11", None),
            ("差旅报销标准与审批流程 v8", "制度域 · 职能", "📗", "published", "李芳", "HIGH", "2026-07-01", None),
            ("支付回调幂等键设计说明", "支付域 · 研发", "📙", "expired", "陈昊", "MEDIUM", "2026-05-20",
             "⚠️ 内容可能与最新资源冲突，检索中已降权，建议 Owner 复核"),
            ("分账能力适用条件与限制", "能力域 · 产品", "📓", "pending_review", "刘洋", "MEDIUM", "2026-07-15", None),
        ]
        for (title, domain, icon, status, owner, conf, pub_date, warning) in knowledge_data:
            kc = KnowledgeCandidate(
                title=title,
                domain=domain,
                department=domain.split(" · ")[-1] if " · " in domain else "",
                icon=icon,
                status=status,
                owner=owner,
                confidence=conf,
                published_at=pub_date,
                conflict_warning=warning,
            )
            session.add(kc)

        await session.commit()
        print("[seed] Mock 数据填充完成")
