"""
总前台路由 -- 接入 AgentRunner（借鉴 nanobot 双层分离）
核心闭环：用户提问 -> 分诊 -> AgentRunner ReAct 循环 -> SSE 流式回答

改造点（对比旧版）：
1. 用 AgentRunner 替代单轮 LLM 调用
2. 注入会话历史（短期记忆）
3. 工具白名单从岗位包加载
4. SSE 增加 tool.start / tool.result 事件
5. 预算追踪（步数/调用数/Token）
"""
import json
from contextlib import AsyncExitStack
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from backend.database import get_db
from backend.models.agent import Agent, RolePack
from backend.models.company import Department, Domain
from backend.models.session import Session, Message
from backend.models.resource import Tool
from backend.runtime.runner import AgentRunner
from backend.runtime.context import build_context, AgentContext
from backend.runtime.tools import build_tool_registry
from backend.runtime.mcp_client import load_mcp_tools

router = APIRouter(prefix="/api/frontdesk", tags=["frontdesk"])

# 关键词 -> 领域名称映射（车联网团队：产品/架构/后端/前端/测试/管理 六个职能领域，
# 未命中的问题回退 _llm_dispatch 由 LLM 按员工描述分诊）
_KEYWORD_MAP = {
    "需求": "产品域", "产品": "产品域", "原型": "产品域", "PRD": "产品域", "用户故事": "产品域",
    "架构": "架构域", "技术选型": "架构域", "高并发": "架构域", "高可用": "架构域",
    "后端": "后端域", "接口": "后端域", "API": "后端域", "服务": "后端域", "数据库": "后端域",
    "经纬度": "后端域", "定位": "后端域", "轨迹": "后端域", "车辆": "后端域", "V2X": "后端域", "v2x": "后端域",
    "前端": "前端域", "页面": "前端域", "大屏": "前端域", "可视化": "前端域", "地图": "前端域",
    "测试": "测试域", "用例": "测试域", "缺陷": "测试域", "BUG": "测试域", "bug": "测试域",
    "进度": "管理域", "计划": "管理域", "排期": "管理域", "资源协调": "管理域",
    "员工": "通用", "同事": "通用", "谁负责": "通用",
}


class ChatRequest(BaseModel):
    """前端聊天请求"""
    question: str
    agent_id: str | None = None
    session_id: str | None = None


class SessionOut(BaseModel):
    """会话列表项（多会话持久化：前端侧栏展示用）"""
    id: str
    title: str
    created_at: str          # ISO 格式时间
    message_count: int
    preview: str             # 最后一条消息前 40 字


class MessageOut(BaseModel):
    """历史消息项（含分诊卡片渲染所需的员工/部门/领域信息）"""
    id: str
    role: str
    content: str
    agent_id: str | None
    agent_name: str
    agent_emoji: str
    department: str
    domain: str
    confidence: str | None
    created_at: str
    feedback: str = ""  # 用户评价: up/down/空(未评价)


async def _run_langchain_agent(question, agent, dept_name, domain_name, session_id, db):
    """
    LangChain/LangGraph Agent 执行路径
    输出与自研 AgentRunner 相同格式的 SSE 事件
    """
    import os as _os

    # 多 Agent 图路径（总台分诊 -> 领域员工）
    if _os.environ.get("USE_MULTI_AGENT", "false").lower() == "true":
        async for evt in _run_multi_agent(question, session_id, db):
            yield evt
        return

    # 单 Agent 路径（总台/指定员工）
    from backend.agents.graph import stream_agent
    from backend.agents.llm import get_llm_no_stream
    from backend.agents.tools import get_all_tools
    from backend.runtime.context import build_system_prompt, AgentContext, Budget

    # 构建 system prompt
    if agent:
        # 领域员工
        role_pack_spec = await _load_role_pack_spec(agent, db)
        context = AgentContext(
            agent=agent,
            session_id=session_id,
            department_name=dept_name,
            domain_name=domain_name,
            role_pack_spec=role_pack_spec,
            allowed_tools=role_pack_spec.get("tools", []),
            resources=agent.resources or role_pack_spec.get("resources", []),
            budget=Budget(
                max_steps=role_pack_spec.get("permission", {}).get("budget", {}).get("steps", 8),
                max_calls=role_pack_spec.get("permission", {}).get("budget", {}).get("calls", 6),
            ),
        )
        system_prompt = build_system_prompt(context)
        agent_name = agent.name
    else:
        # 总台自答
        import uuid as _uuid
        frontdesk_agent = Agent(
            id=_uuid.uuid4().hex, name="总前台", title="总台分诊员", emoji="🎯",
            description="Agent 办公室的总前台，负责接收用户问题、分诊到对口员工。当无法匹配到具体领域员工时，使用工具查询公司信息并回答。",
            status="online",
        )
        context = AgentContext(
            agent=frontdesk_agent,
            session_id=session_id,
            department_name="总前台",
            domain_name="通用",
            role_pack_spec={"tools": [], "permission": {"read_only": True}},
            budget=Budget(),
        )
        system_prompt = build_system_prompt(context)
        agent_name = "总前台"

    full_answer = ""
    tools_used = []

    # 流式执行 LangGraph Agent
    async for event in stream_agent(
        question=question,
        system_prompt=system_prompt,
        history=[],  # TODO: 从 Message 表加载历史
        tools=get_all_tools(),
        max_iterations=8,
    ):
        evt_type = event.get("type")

        if evt_type == "tool.start":
            yield _sse_event("tool.start", {
                "name": event["name"],
                "arguments": event.get("arguments", {}),
            })

        elif evt_type == "tool.result":
            yield _sse_event("tool.result", {
                "name": event["name"],
                "result": event.get("result", ""),
                "is_error": event.get("is_error", False),
            })

        elif evt_type == "answer.chunk":
            full_answer += event.get("content", "")
            yield _sse_event("answer.chunk", {"content": event.get("content", "")})

        elif evt_type == "answer.completed":
            # 持久化 AI 回答
            message_id = await _save_message(session_id, "assistant", full_answer, agent.id if agent else None, db, confidence="中")
            yield _sse_event("answer.completed", {
                "full_answer": full_answer,
                "agent_name": agent_name,
                "tools_used": event.get("tools_used", tools_used),
                "iterations": event.get("iterations", 0),
                "session_id": session_id,
                "message_id": message_id,
            })
            return

        elif evt_type == "error":
            yield _sse_event("error", {"message": event.get("message", "未知错误")})
            return


def _sse_event(event_type: str, data: dict) -> str:
    """构造 SSE 事件字符串"""
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _match_domains(question: str) -> list[str]:
    """统计问题命中的业务领域(关键词表),>=2 个时建议转为协作任务"""
    matched = {domain for kw, domain in _KEYWORD_MAP.items() if kw in question and domain != "通用"}
    return sorted(matched)


async def _run_multi_agent(question, session_id, db):
    """
    多 Agent 图执行路径（总台分诊 -> 领域员工）
    输出与单 Agent 相同格式的 SSE 事件
    """
    from backend.agents.multi_agent import run_multi_agent

    try:
        result = await run_multi_agent(question)

        agent_name = result.get("agent_name", "总前台")
        dept_name = result.get("dept_name", "")
        domain_name = result.get("domain_name", "")
        answer = result.get("answer", "")
        tools_used = result.get("tools_used", [])
        route_reason = result.get("route_reason", "")

        # 路由决策事件
        yield _sse_event("route.decided", {
            "agent_id": None,
            "agent_name": agent_name,
            "agent_emoji": "🎯" if agent_name == "总前台" else "🧑‍💻",
            "department": dept_name,
            "domain": domain_name,
            "self_answered": agent_name == "总前台",
            "reason": route_reason,
            "confidence": "中",
        })

        # 分块流式输出
        for i in range(0, len(answer), 20):
            chunk = answer[i:i+20]
            yield _sse_event("answer.chunk", {"content": chunk})

        # 持久化
        message_id = await _save_message(session_id, "assistant", answer, None, db, confidence="中")

        # 完成
        yield _sse_event("answer.completed", {
            "full_answer": answer,
            "agent_name": agent_name,
            "tools_used": tools_used,
            "iterations": 1,
            "session_id": session_id,
            "message_id": message_id,
        })

    except Exception as e:
        yield _sse_event("error", {"message": str(e)})


async def _find_best_agent(question: str, db: AsyncSession) -> tuple[Agent | None, str, str, str]:
    """
    分诊：根据问题匹配领域，返回最佳员工 + 部门名 + 领域名 + 路由原因
    TODO: 后续改为 LLM 驱动分诊（借鉴 nanobot Subagent 的思路）
    """
    matched_domains = []
    for kw, domain_name in _KEYWORD_MAP.items():
        if kw in question and domain_name not in matched_domains:
            matched_domains.append(domain_name)

    if not matched_domains:
        return None, "", "", ""

    all_domains = (await db.execute(select(Domain))).scalars().all()
    all_depts = (await db.execute(select(Department))).scalars().all()
    all_agents = (await db.execute(select(Agent))).scalars().all()

    dept_map = {d.id: d.name for d in all_depts}

    for dm in all_domains:
        if dm.name in matched_domains:
            for agent in all_agents:
                if agent.domain_id == dm.id and agent.status in ("online", "trial"):
                    return agent, dept_map.get(agent.department_id, ""), dm.name, f"关键词命中领域:{dm.name}"

    return None, "", "", ""


async def _find_agent_by_repo(question: str, db: AsyncSession) -> tuple[Agent | None, str, str, str]:
    """
    仓库名直路由：问题中显式提到仓库名时，反查 AgentRepoBinding 找绑定员工直接路由
    （零 LLM 调用，最快路径；绑定多人时按绑定顺序取第一个）
    """
    from backend.models.governance import AgentRepoBinding, Repository

    repos = (await db.execute(select(Repository))).scalars().all()
    if not repos:
        return None, "", "", ""

    # 问题文本命中仓库名（长名优先，避免短名误命中）
    hit = None
    for r in sorted(repos, key=lambda x: -len(x.name or "")):
        if r.name and r.name in question:
            hit = r
            break
    if not hit:
        return None, "", "", ""

    # 反查绑定员工（online/trial，保持绑定顺序取第一个）
    bindings = (await db.execute(
        select(AgentRepoBinding).where(AgentRepoBinding.repo_id == hit.id)
    )).scalars().all()
    if not bindings:
        return None, "", "", ""

    agent_ids = [b.agent_id for b in bindings]
    agents = (await db.execute(
        select(Agent).where(Agent.id.in_(agent_ids), Agent.status.in_(["online", "trial"]))
    )).scalars().all()
    if not agents:
        return None, "", "", ""

    order = {aid: i for i, aid in enumerate(agent_ids)}
    agents.sort(key=lambda a: order.get(a.id, 999))
    agent = agents[0]

    dept = (await db.execute(
        select(Department).where(Department.id == agent.department_id)
    )).scalar_one_or_none()
    dm = (await db.execute(
        select(Domain).where(Domain.id == agent.domain_id)
    )).scalar_one_or_none()

    return agent, (dept.name if dept else ""), (dm.name if dm else ""), f"仓库绑定:{hit.name}"


async def _llm_dispatch(question: str, db: AsyncSession) -> tuple[Agent | None, str, str, str]:
    """
    LLM 驱动分诊（替代关键词硬编码）
    借鉴 nanobot 哲学：把路由决策交给 LLM

    流程：
    1. 查询所有可用员工 + 部门 + 领域 + 绑定仓库/能力
    2. 构建精简 prompt，让 LLM 输出 JSON 路由决策
    3. 解析并返回匹配的 Agent + 路由原因
    """
    import json as _json
    from sqlalchemy import or_ as _or
    from backend.models.governance import AgentRepoBinding, Repository
    from backend.models.resource import Skill

    # 查询所有可用员工
    all_agents = (await db.execute(
        select(Agent).where(Agent.status.in_(["online", "trial"]))
    )).scalars().all()
    if not all_agents:
        return None, "", "", ""

    all_domains = (await db.execute(select(Domain))).scalars().all()
    all_depts = (await db.execute(select(Department))).scalars().all()
    dept_map = {d.id: d.name for d in all_depts}
    domain_map = {d.id: d.name for d in all_domains}

    # 批量查仓库绑定（一次 IN 查询，避免 N+1）
    agent_ids = [a.id for a in all_agents]
    bindings = (await db.execute(
        select(AgentRepoBinding).where(AgentRepoBinding.agent_id.in_(agent_ids))
    )).scalars().all()
    repo_ids = list({b.repo_id for b in bindings})
    repo_map = {}
    if repo_ids:
        repos = (await db.execute(
            select(Repository).where(Repository.id.in_(repo_ids))
        )).scalars().all()
        repo_map = {r.id: r.name for r in repos}
    agent_repos: dict[str, list[str]] = {}
    for b in bindings:
        rname = repo_map.get(b.repo_id)
        if rname and rname not in agent_repos.setdefault(b.agent_id, []):
            agent_repos[b.agent_id].append(rname)

    # 批量查能力名称（skill_key 与名称双兼容）
    all_skill_keys = {k for a in all_agents for k in (a.skills or [])}
    skill_name_map: dict[str, str] = {}
    if all_skill_keys:
        skills = (await db.execute(
            select(Skill).where(_or(Skill.skill_key.in_(all_skill_keys), Skill.name.in_(all_skill_keys)))
        )).scalars().all()
        for s in skills:
            skill_name_map[s.skill_key] = s.name
            skill_name_map[s.name] = s.name

    # 构建员工列表（精简：repos/skills 让 LLM 能把代码问题路由到绑定员工）
    agent_list = []
    for a in all_agents:
        agent_list.append({
            "id": a.id,
            "name": a.name,
            "title": a.title,
            "department": dept_map.get(a.department_id, ""),
            "domain": domain_map.get(a.domain_id, ""),
            "description": (a.description or "")[:80],
            "repos": agent_repos.get(a.id, [])[:5],
            "skills": [skill_name_map.get(k, k) for k in (a.skills or [])][:8],
        })

    # 构建 LLM 分诊 prompt
    dispatch_prompt = f"""你是 Agent 办公室的总台分诊员。根据用户问题，选择最合适的员工来回答。

## 可用员工列表
{_json.dumps(agent_list, ensure_ascii=False, indent=2)}

## 用户问题
{question}

## 输出要求
返回 JSON 格式（不要其他内容）：
- 如果有匹配的员工：{{"agent_id": "员工ID", "reason": "选择原因"}}
- 如果没有匹配的：{{"agent_id": null, "reason": "无匹配员工"}}

选择标准：
1. 员工的专业领域与问题最相关
2. 员工的职责描述能覆盖问题范围
3. 如果问题涉及多个领域，选择最相关的那个
4. 代码/仓库相关问题优先选择绑定了对应仓库(repos)的员工"""

    try:
        from backend.services.llm import chat_completion
        from backend.services.skill_validator import extract_llm_json
        messages = [{"role": "user", "content": dispatch_prompt}]
        # GLM 为推理模型,思考耗 token 且长度波动大,预算给足;空返回重试一次兜底
        result = ""
        for _ in range(2):
            result = await chat_completion(messages, temperature=0.1, max_tokens=2000)
            if result and result.strip():
                break
            print("[dispatch] LLM 分诊返回空,重试")

        # 解析 LLM 输出(复用容错提取:剥围栏/截取首尾花括号)
        decision = extract_llm_json(result) if result else None
        if decision is None:
            print(f"[dispatch] LLM 分诊输出非 JSON: {result[:200]!r}")
            return None, "", "", ""
        agent_id = decision.get("agent_id")
        reason = decision.get("reason", "")

        if agent_id:
            for a in all_agents:
                if a.id == agent_id:
                    return a, dept_map.get(a.department_id, ""), domain_map.get(a.domain_id, ""), reason
        return None, "", "", reason or "LLM 分诊无匹配"

    except Exception as e:
        print(f"[dispatch] LLM 分诊失败: {e}")

    return None, "", "", ""


async def _load_role_pack_spec(agent: Agent, db: AsyncSession) -> dict:
    """
    加载岗位包配置（从 RolePack 表）
    如果 Agent 有 role_pack_id，加载对应的 RolePack.config
    否则返回默认配置
    """
    if not agent.role_pack_id:
        # 默认配置：全部内置工具 + 默认预算
        return {
            "tools": ["searchKnowledge", "getEmployeeInfo", "searchResource", "loadSkill", "searchCode", "getCodeExcerpt", "listFiles", "cloneRepo", "getProjectStructure", "searchInDocs"],
            "skills": [],
            "resources": agent.resources or [],
            "permission": {
                "read_only": True,
                "acl_mode": "whitelist",
                "budget": {"steps": 8, "calls": 6, "timeout": 60, "token": 48000},
            },
        }

    result = await db.execute(select(RolePack).where(RolePack.id == agent.role_pack_id))
    rp = result.scalar_one_or_none()
    if not rp:
        return {"tools": [], "skills": [], "resources": []}

    spec = rp.config or {}
    # 确保有 tools 字段
    if "tools" not in spec:
        spec["tools"] = ["searchKnowledge", "getEmployeeInfo", "searchResource", "loadSkill", "searchCode", "getCodeExcerpt", "listFiles", "cloneRepo", "getProjectStructure", "searchInDocs"]
    return spec


async def _get_or_create_session(session_id: str | None, db: AsyncSession) -> str:
    """获取或创建会话（确保 session 在数据库中存在，避免外键约束失败）"""
    import uuid

    # 如果前端传了 session_id，先检查数据库中是否存在
    if session_id:
        existing = await db.execute(select(Session).where(Session.id == session_id))
        if existing.scalar_one_or_none():
            return session_id  # 已存在，直接用
        # 不存在 → 创建一条（用前端传的 ID）
        session = Session(id=session_id, user_id="guest", title="总前台对话", state="active")
        db.add(session)
        # 立即 commit 释放行锁：SSE 流式期间若只 flush，事务会横跨整个 LLM 调用（数十秒），
        # MySQL REPEATABLE READ 下会阻塞其它请求的 INSERT（锁等待超时）
        await db.commit()
        return session_id

    # 没传 session_id → 创建新的
    session = Session(id=uuid.uuid4().hex, user_id="guest", title="总前台对话", state="active")
    db.add(session)
    await db.commit()  # 同上：立即释放锁
    return session.id


async def _save_message(
    session_id: str,
    role: str,
    content: str,
    agent_id: str | None,
    db: AsyncSession,
    confidence: str | None = None,
) -> str:
    """将消息持久化到 Message 表（历史记忆），返回消息 id（前端点赞/点踩需要）"""
    import uuid
    msg = Message(
        id=uuid.uuid4().hex,
        session_id=session_id,
        role=role,
        content=content,
        agent_id=agent_id,
        confidence=confidence,
    )
    db.add(msg)
    await db.commit()  # 消息属流水型数据，立即提交释放锁（流式期间不能长持事务）
    return msg.id


@router.post("/chat")
async def chat(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    """
    SSE 流式问答端点（接入 AgentRunner）
    事件流：
      route.decided -> tool.start -> tool.result(可多轮) -> answer.chunk(多个) -> answer.completed
    """
    question = req.question
    # 跨领域检测:命中 >=2 个领域时,answer.completed 携带 suggest_collab 提示前端展示「转为协作任务」
    suggest_collab = _match_domains(question)
    suggest_collab = suggest_collab if len(suggest_collab) >= 2 else []

    async def event_stream():
        try:
            # === 1. 分诊 ===
            agent = None
            dept_name = ""
            domain_name = ""
            reason = ""

            if req.agent_id:
                result = await db.execute(select(Agent).where(Agent.id == req.agent_id))
                agent = result.scalar_one_or_none()
                if agent:
                    dept_res = await db.execute(select(Department).where(Department.id == agent.department_id))
                    dept = dept_res.scalar_one_or_none()
                    dm_res = await db.execute(select(Domain).where(Domain.id == agent.domain_id))
                    dm = dm_res.scalar_one_or_none()
                    dept_name = dept.name if dept else ""
                    domain_name = dm.name if dm else ""
                    reason = "指定员工直路由"
            else:
                # 三级分诊链：关键词命中领域 -> 仓库名直路由 -> LLM 分诊
                agent, dept_name, domain_name, reason = await _find_best_agent(question, db)
                if not agent:
                    agent, dept_name, domain_name, reason = await _find_agent_by_repo(question, db)
                if not agent:
                    agent, dept_name, domain_name, reason = await _llm_dispatch(question, db)

            # 发送路由决策事件
            if agent:
                yield _sse_event("route.decided", {
                    "agent_id": agent.id,
                    "agent_name": agent.name,
                    "agent_emoji": agent.emoji,
                    "department": dept_name,
                    "domain": domain_name,
                    "self_answered": False,
                    "confidence": "中",
                    "reason": reason,
                })
            else:
                yield _sse_event("route.decided", {
                    "agent_id": None,
                    "agent_name": "总前台",
                    "agent_emoji": "🎯",
                    "department": "总前台",
                    "domain": "通用",
                    "self_answered": True,
                    "confidence": "中",
                    "reason": "无匹配员工，总前台自答",
                })

            # === 2. 构建 Agent 执行环境 ===
            session_id = await _get_or_create_session(req.session_id, db)

            # 保存用户消息
            await _save_message(session_id, "user", question, None, db)

            # 首次提问时用问题更新会话标题（默认标题 "总前台对话" 才覆盖）
            sess_res = await db.execute(select(Session).where(Session.id == session_id))
            sess_obj = sess_res.scalar_one_or_none()
            if sess_obj and sess_obj.title == "总前台对话":
                sess_obj.title = question[:20] + ("…" if len(question) > 20 else "")
                await db.commit()  # 标题更新也立即提交

            # ===== LangChain/LangGraph 路径（feature flag 切换）=====
            import os as _os
            if _os.environ.get("USE_LANGCHAIN", "false").lower() == "true":
                async for evt in _run_langchain_agent(question, agent, dept_name, domain_name, session_id, db):
                    yield evt
                return

            # ===== 自研 AgentRunner 路径（默认）=====
            if agent:
                # 加载岗位包配置
                role_pack_spec = await _load_role_pack_spec(agent, db)

                # 构建上下文（含历史注入）
                context = await build_context(
                    agent=agent,
                    session_id=session_id,
                    db=db,
                    role_pack_spec=role_pack_spec,
                    dept_name=dept_name,
                    domain_name=domain_name,
                )

                # 构建工具注册表（从岗位包白名单，注入绑定仓库/领域作用域）
                tool_registry = build_tool_registry(
                    context.allowed_tools,
                    allowed_repos=context.allowed_repos,
                    default_repo=context.default_repo,
                    default_domain=domain_name,
                )

                # MCP Server 工具：会话生命周期必须覆盖整个流式消费过程
                # （stack 不能建在 load_mcp_tools 内部，否则 list_tools 后会话即关，call_tool 失败）
                async with AsyncExitStack() as mcp_stack:
                    for mcp_tool in await load_mcp_tools(mcp_stack, context.allowed_tools, db):
                        tool_registry.register(mcp_tool)

                    # 执行 AgentRunner 流式循环
                    runner = AgentRunner()

                    full_answer = ""
                    async for event in runner.execute_stream(question, context, tool_registry, db=db):
                        evt_type = event.get("type")

                        if evt_type == "tool.start":
                            yield _sse_event("tool.start", {
                                "name": event["name"],
                                "arguments": event.get("arguments", {}),
                            })

                        elif evt_type == "tool.result":
                            yield _sse_event("tool.result", {
                                "name": event["name"],
                                "result": event.get("result", ""),
                                "is_error": event.get("is_error", False),
                            })

                        elif evt_type == "answer.chunk":
                            full_answer += event["content"]
                            yield _sse_event("answer.chunk", {"content": event["content"]})

                        elif evt_type == "answer.completed":
                            full_answer = event.get("final_content", full_answer)
                            # 持久化 AI 回答
                            message_id = await _save_message(session_id, "assistant", full_answer, agent.id, db, confidence="中")
                            yield _sse_event("answer.completed", {
                                "full_answer": full_answer,
                                "agent_name": agent.name,
                                "tools_used": event.get("tools_used", []),
                                "iterations": event.get("iterations", 0),
                                "session_id": session_id,
                                "suggest_collab": suggest_collab,
                                "message_id": message_id,
                            })
                            return

                        elif evt_type == "error":
                            yield _sse_event("error", {"message": event.get("message", "未知错误")})
                            return

            else:
                # 总前台自答（也走 AgentRunner + 全部工具）
                # 创建虚拟总台 Agent
                import uuid as _uuid
                frontdesk_agent = Agent(
                    id=_uuid.uuid4().hex,
                    name="总前台",
                    title="总台分诊员",
                    emoji="🎯",
                    description="Agent 办公室的总前台，负责接收用户问题、分诊到对口员工。当无法匹配到具体领域员工时，使用工具查询公司信息并回答。",
                    status="online",
                )

                # 总台拥有全部工具：内置工具 + 所有已接入的 MCP Server
                # （MCP Server 名单从 Tool 表动态加载，新接入的 MCP 无需改代码即可被总台使用）
                builtin_tools = ["searchKnowledge", "getEmployeeInfo", "searchResource", "loadSkill", "searchCode", "getCodeExcerpt", "listFiles", "cloneRepo", "getProjectStructure", "searchInDocs"]
                mcp_rows = (await db.execute(
                    select(Tool.name).where(Tool.type == "mcp", Tool.state == "APPROVED")
                )).scalars().all()
                frontdesk_spec = {
                    "tools": builtin_tools + list(mcp_rows),
                    "skills": [],
                    "resources": [],
                    "permission": {
                        "read_only": True,
                        "acl_mode": "whitelist",
                        "budget": {"steps": 8, "calls": 6, "timeout": 60, "token": 48000},
                    },
                }

                context = await build_context(
                    agent=frontdesk_agent,
                    session_id=session_id,
                    db=db,
                    role_pack_spec=frontdesk_spec,
                    dept_name="总前台",
                    domain_name="通用",
                )

                tool_registry = build_tool_registry(
                    context.allowed_tools,
                    allowed_repos=context.allowed_repos,
                    default_repo=context.default_repo,
                    default_domain=domain_name,
                )

                # MCP Server 工具（总台 spec 全是内置工具名，正常返回空列表，零成本兼容）
                async with AsyncExitStack() as mcp_stack:
                    for mcp_tool in await load_mcp_tools(mcp_stack, context.allowed_tools, db):
                        tool_registry.register(mcp_tool)

                    runner = AgentRunner()

                    full_answer = ""
                    async for event in runner.execute_stream(question, context, tool_registry, db=db):
                        evt_type = event.get("type")

                        if evt_type == "tool.start":
                            yield _sse_event("tool.start", {
                                "name": event["name"],
                                "arguments": event.get("arguments", {}),
                            })
                        elif evt_type == "tool.result":
                            yield _sse_event("tool.result", {
                                "name": event["name"],
                                "result": event.get("result", ""),
                                "is_error": event.get("is_error", False),
                            })
                        elif evt_type == "answer.chunk":
                            full_answer += event["content"]
                            yield _sse_event("answer.chunk", {"content": event["content"]})
                        elif evt_type == "answer.completed":
                            full_answer = event.get("final_content", full_answer)
                            message_id = await _save_message(session_id, "assistant", full_answer, None, db, confidence="中")
                            yield _sse_event("answer.completed", {
                                "full_answer": full_answer,
                                "agent_name": "总前台",
                                "tools_used": event.get("tools_used", []),
                                "iterations": event.get("iterations", 0),
                                "session_id": session_id,
                                "suggest_collab": suggest_collab,
                                "message_id": message_id,
                            })
                            return
                        elif evt_type == "error":
                            yield _sse_event("error", {"message": event.get("message", "未知错误")})
                            return

        except Exception as e:
            yield _sse_event("error", {"message": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class FeedbackRequest(BaseModel):
    """回答评价请求: up=有用 down=需要改进 空串=取消评价"""
    feedback: str


@router.post("/messages/{message_id}/feedback")
async def submit_feedback(message_id: str, req: FeedbackRequest, db: AsyncSession = Depends(get_db)):
    """记录用户对某条回答的点赞/点踩(总览采纳率的真实数据源)"""
    if req.feedback not in ("up", "down", ""):
        return {"ok": False, "error": "feedback 仅支持 up/down/空"}
    result = await db.execute(select(Message).where(Message.id == message_id))
    msg = result.scalar_one_or_none()
    if not msg or msg.role != "assistant":
        return {"ok": False, "error": "消息不存在或非回答消息"}
    msg.feedback = req.feedback
    await db.commit()  # 立即提交,看板聚合依赖数据可见性
    return {"ok": True, "feedback": msg.feedback}


@router.post("/ask")
async def ask_question(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    """分诊预览：返回匹配的部门和员工（关键词 -> 仓库直路由，不调 LLM）"""
    agent, dept_name, domain_name, reason = await _find_best_agent(req.question, db)
    if not agent:
        agent, dept_name, domain_name, reason = await _find_agent_by_repo(req.question, db)
    return {
        "question": req.question,
        "agent": {
            "id": agent.id,
            "name": agent.name,
            "emoji": agent.emoji,
            "role": agent.title,
            "department": dept_name,
            "domain": domain_name,
        } if agent else None,
        "reason": reason,
        "message": f"已分诊到 {dept_name}/{domain_name}" if agent else "未匹配到具体领域，总前台将自答",
    }


@router.get("/quick-questions")
async def get_quick_questions():
    """获取快捷提问列表"""
    return [
        "创建订单该调用哪个接口？幂等怎么处理？",
        "退款超时该怎么处理？",
        "差旅报销标准与审批流程是什么？",
        "公司有哪些员工？各自的职责是什么？",
        "搜索一下知识库里关于支付回调的文档",
    ]


# ============================================================
# 多会话持久化：会话列表 / 历史消息 / 删除会话
# ============================================================

@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(db: AsyncSession = Depends(get_db)):
    """获取当前用户（guest）的会话列表，按创建时间倒序"""
    sess_res = await db.execute(
        select(Session)
        .where(Session.user_id == "guest", Session.state == "active")
        .order_by(Session.created_at.desc())
        .limit(50)
    )
    sessions = sess_res.scalars().all()
    if not sessions:
        return []

    session_ids = [s.id for s in sessions]

    # 一次性统计各会话消息数（避免 N+1）
    cnt_res = await db.execute(
        select(Message.session_id, func.count(Message.id))
        .where(Message.session_id.in_(session_ids))
        .group_by(Message.session_id)
    )
    cnt_map = dict(cnt_res.all())

    # 取每个会话的最后一条消息做预览（消息量小，逐会话查 limit 1 可接受）
    preview_map: dict[str, str] = {}
    for sid in session_ids:
        msg_res = await db.execute(
            select(Message.content)
            .where(Message.session_id == sid)
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        last = msg_res.scalar_one_or_none()
        preview_map[sid] = (last or "")[:40]

    return [
        SessionOut(
            id=s.id,
            title=s.title,
            created_at=s.created_at.isoformat() if s.created_at else "",
            message_count=cnt_map.get(s.id, 0),
            preview=preview_map.get(s.id, ""),
        )
        for s in sessions
    ]


@router.get("/sessions/{session_id}/messages", response_model=list[MessageOut])
async def get_session_messages(session_id: str, db: AsyncSession = Depends(get_db)):
    """获取会话历史消息（升序，最多 200 条），含分诊卡片所需的员工/部门/领域信息"""
    msg_res = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.asc())
        .limit(200)
    )
    messages = msg_res.scalars().all()

    # 批量查 Agent（避免 N+1）
    agent_ids = {m.agent_id for m in messages if m.agent_id}
    agent_map: dict[str, Agent] = {}
    dept_map: dict[str, str] = {}
    domain_map: dict[str, str] = {}
    if agent_ids:
        ag_res = await db.execute(select(Agent).where(Agent.id.in_(agent_ids)))
        agents = ag_res.scalars().all()
        agent_map = {a.id: a for a in agents}
        # 批量查部门/领域名称
        dept_ids = {a.department_id for a in agents if a.department_id}
        domain_ids = {a.domain_id for a in agents if a.domain_id}
        if dept_ids:
            d_res = await db.execute(select(Department).where(Department.id.in_(dept_ids)))
            dept_map = {d.id: d.name for d in d_res.scalars().all()}
        if domain_ids:
            dm_res = await db.execute(select(Domain).where(Domain.id.in_(domain_ids)))
            domain_map = {d.id: d.name for d in dm_res.scalars().all()}

    result: list[MessageOut] = []
    for m in messages:
        if m.agent_id:
            agent = agent_map.get(m.agent_id)
            if agent:
                # 员工仍在职：带出真实信息
                agent_name, agent_emoji = agent.name, agent.emoji or "🧑‍💻"
                department = dept_map.get(agent.department_id, "")
                domain = domain_map.get(agent.domain_id, "")
            else:
                # 员工已删除：降级展示
                agent_name, agent_emoji, department, domain = "已离职员工", "🧑‍💻", "", ""
        else:
            # agent_id 为空：总前台自答
            agent_name, agent_emoji, department, domain = "总前台", "🎯", "总前台", "通用"
        result.append(MessageOut(
            id=m.id,
            role=m.role,
            content=m.content,
            agent_id=m.agent_id,
            agent_name=agent_name,
            agent_emoji=agent_emoji,
            department=department,
            domain=domain,
            confidence=m.confidence,
            created_at=m.created_at.isoformat() if m.created_at else "",
            feedback=m.feedback or "",
        ))
    return result


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, db: AsyncSession = Depends(get_db)):
    """删除会话及其全部消息（幂等：不存在也返回 ok）"""
    await db.execute(delete(Message).where(Message.session_id == session_id))
    await db.execute(delete(Session).where(Session.id == session_id))
    await db.commit()
    return {"ok": True}
