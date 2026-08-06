"""
⚠️ 已废弃：生产路由统一在 backend/routers/frontdesk.py（三级分诊链 + ReAct 循环），
本文件仅为 LangGraph 旁路（USE_MULTI_AGENT=true 才触发），勿在此基础上做新开发。

多 Agent 图 - 总台分诊 -> 领域员工
实现 PRD 中的"总前台 + 部门对接人两级分诊"

图结构：
  dispatcher（总台分诊，LLM 决策）
    ├── route -> agent（领域员工 ReAct）
    └── route -> frontdesk（总台自答）

关键设计：
1. dispatcher 查询员工列表，用 LLM 输出路由决策
2. 路由函数根据决策返回节点名（agent 或 frontdesk）
3. agent 节点根据 agent_id 构建对应 system prompt + 工具，执行 ReAct
4. frontdesk 节点用全工具自答
"""
import json
from typing import TypedDict
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END

from backend.agents.llm import get_llm, get_llm_no_stream
from backend.agents.tools import get_all_tools
from backend.agents.graph import build_agent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.agent import Agent
from backend.models.company import Department, Domain


class MultiAgentState(TypedDict):
    """多 Agent 状态"""
    question: str
    agent_id: str  # 分诊结果（员工 ID 或空）
    agent_name: str
    dept_name: str
    domain_name: str
    route_reason: str
    messages: list
    answer: str
    tools_used: list[str]


async def _llm_dispatch(question: str, db: AsyncSession) -> dict:
    """
    LLM 分诊：查询员工列表，用 LLM 输出路由决策
    返回 {"agent_id": "xxx", "agent_name": "xxx", "dept": "xxx", "domain": "xxx", "reason": "xxx"}
    """
    all_agents = (await db.execute(
        select(Agent).where(Agent.status.in_(["online", "trial"]))
    )).scalars().all()

    if not all_agents:
        return {"agent_id": None, "agent_name": "总前台", "dept": "总前台", "domain": "通用", "reason": "无可用员工"}

    all_domains = (await db.execute(select(Domain))).scalars().all()
    all_depts = (await db.execute(select(Department))).scalars().all()
    dept_map = {d.id: d.name for d in all_depts}
    domain_map = {d.id: d.name for d in all_domains}

    # 构建员工列表
    agent_list = []
    for a in all_agents:
        agent_list.append({
            "id": a.id, "name": a.name, "title": a.title,
            "department": dept_map.get(a.department_id, ""),
            "domain": domain_map.get(a.domain_id, ""),
            "description": (a.description or "")[:100],
        })

    # LLM 分诊 prompt
    dispatch_prompt = f"""你是 Agent 办公室的总台分诊员。根据用户问题，选择最合适的员工来回答。

## 可用员工列表
{json.dumps(agent_list, ensure_ascii=False, indent=2)}

## 用户问题
{question}

## 输出要求（只返回 JSON，不要其他内容）
- 如果有匹配的员工：{{"agent_id": "员工ID", "reason": "选择原因"}}
- 如果没有匹配的：{{"agent_id": null, "reason": "无匹配员工"}}

选择标准：
1. 员工的专业领域与问题最相关
2. 员工的职责描述能覆盖问题范围
3. 如果问题涉及多个领域，选择最相关的那个"""

    try:
        llm = get_llm_no_stream(temperature=0.1, max_tokens=200)
        result = await llm.ainvoke([HumanMessage(content=dispatch_prompt)])
        text = result.content.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]

        decision = json.loads(text.strip())
        agent_id = decision.get("agent_id")

        if agent_id:
            for a in all_agents:
                if a.id == agent_id:
                    return {
                        "agent_id": a.id,
                        "agent_name": a.name,
                        "dept": dept_map.get(a.department_id, ""),
                        "domain": domain_map.get(a.domain_id, ""),
                        "reason": decision.get("reason", ""),
                    }

    except Exception as e:
        print(f"[dispatch] LLM 分诊失败: {e}")

    return {"agent_id": None, "agent_name": "总前台", "dept": "总前台", "domain": "通用", "reason": "无匹配员工"}


def build_multi_agent_graph():
    """构建多 Agent 图"""

    # dispatcher 节点：总台分诊
    async def dispatcher_node(state: MultiAgentState) -> dict:
        from backend.database import async_session
        async with async_session() as db:
            route = await _llm_dispatch(state["question"], db)

        return {
            "agent_id": route.get("agent_id"),
            "agent_name": route.get("agent_name", "总前台"),
            "dept_name": route.get("dept", ""),
            "domain_name": route.get("domain", ""),
            "route_reason": route.get("reason", ""),
        }

    # agent 节点：领域员工执行 ReAct
    async def agent_node(state: MultiAgentState) -> dict:
        from backend.database import async_session
        from backend.models.agent import Agent
        from backend.runtime.context import build_system_prompt, AgentContext, Budget

        async with async_session() as db:
            # 查询员工信息
            result = await db.execute(select(Agent).where(Agent.id == state["agent_id"]))
            agent = result.scalar_one_or_none()

            if not agent:
                return {"answer": "员工不存在", "tools_used": []}

            # 构建 system prompt
            context = AgentContext(
                agent=agent,
                session_id="multi_agent",
                department_name=state["dept_name"],
                domain_name=state["domain_name"],
                role_pack_spec={"tools": [], "permission": {"read_only": True}},
                budget=Budget(),
            )
            system_prompt = build_system_prompt(context)

        # 执行 ReAct Agent
        react_agent = build_agent(system_prompt, get_all_tools())
        result = await react_agent.ainvoke({"messages": [
            SystemMessage(content=system_prompt),
            HumanMessage(content=state["question"]),
        ]})

        last_msg = result["messages"][-1]
        answer = last_msg.content if hasattr(last_msg, "content") else str(last_msg)

        tools_used = []
        for msg in result["messages"]:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    tools_used.append(tc.get("name", "unknown"))

        return {"answer": answer, "tools_used": tools_used}

    # frontdesk 节点：总台自答（全工具）
    async def frontdesk_node(state: MultiAgentState) -> dict:
        system_prompt = """你是 Agent 办公室的总前台。用户的问题没有匹配到具体领域员工，
请使用工具查询公司信息并回答。如果信息不足，建议用户更具体地描述问题。"""

        react_agent = build_agent(system_prompt, get_all_tools())
        result = await react_agent.ainvoke({"messages": [
            SystemMessage(content=system_prompt),
            HumanMessage(content=state["question"]),
        ]})

        last_msg = result["messages"][-1]
        answer = last_msg.content if hasattr(last_msg, "content") else str(last_msg)

        tools_used = []
        for msg in result["messages"]:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    tools_used.append(tc.get("name", "unknown"))

        return {"answer": answer, "tools_used": tools_used}

    # 路由函数：根据分诊结果决定下一步
    def route_after_dispatch(state: MultiAgentState) -> str:
        if state.get("agent_id"):
            return "agent"
        return "frontdesk"

    # 构建图
    graph = StateGraph(MultiAgentState)

    graph.add_node("dispatcher", dispatcher_node)
    graph.add_node("agent", agent_node)
    graph.add_node("frontdesk", frontdesk_node)

    graph.set_entry_point("dispatcher")

    graph.add_conditional_edges(
        "dispatcher",
        route_after_dispatch,
        {
            "agent": "agent",
            "frontdesk": "frontdesk",
        },
    )

    graph.add_edge("agent", END)
    graph.add_edge("frontdesk", END)

    return graph.compile()


async def run_multi_agent(question: str) -> dict:
    """执行多 Agent 图（非流式）"""
    app = build_multi_agent_graph()
    result = await app.ainvoke({"question": question})

    return {
        "answer": result.get("answer", ""),
        "agent_name": result.get("agent_name", "总前台"),
        "dept_name": result.get("dept_name", ""),
        "domain_name": result.get("domain_name", ""),
        "route_reason": result.get("route_reason", ""),
        "tools_used": result.get("tools_used", []),
    }
