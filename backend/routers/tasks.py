"""
协作会议室路由
从 MySQL 读取任务卡与子任务分配
支持发起协作:LLM 拆解子任务 -> 多员工并行执行 -> 汇总并显式标注冲突
"""
import asyncio
import json
import uuid
from contextlib import AsyncExitStack
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db, async_session
from backend.models.agent import Agent
from backend.models.company import Department, Domain
from backend.models.task import TaskCard, TaskAssignment

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

# 冲突类型映射
def _conflict_type(note: str | None) -> str:
    if not note:
        return "warning"
    return "success" if note.startswith("✅") else "warning"


@router.get("")
async def list_tasks(
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """获取协作任务列表，可按状态筛选"""
    query = select(TaskCard).options(selectinload(TaskCard.assignments))
    if status:
        query = query.where(TaskCard.state == status)
    query = query.order_by(TaskCard.created_at.desc())

    result = await db.execute(query)
    tasks = result.scalars().all()

    return [_task_to_dict(t) for t in tasks]


@router.get("/{task_id}")
async def get_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """获取单个任务详情（含子任务）"""
    result = await db.execute(
        select(TaskCard)
        .options(selectinload(TaskCard.assignments))
        .where(TaskCard.id == task_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _task_to_dict(task)


@router.get("/{task_id}/doc")
async def get_task_doc(task_id: str, db: AsyncSession = Depends(get_db)):
    """获取协作任务的完整方案 md（讨论合成产物，落盘于 workspaces/collab_docs/）"""
    from backend.services.file_service import read_collab_doc

    exists = (await db.execute(
        select(TaskCard.id).where(TaskCard.id == task_id)
    )).scalar_one_or_none()
    if not exists:
        raise HTTPException(status_code=404, detail="任务不存在")
    content = read_collab_doc(task_id)
    if content is None:
        raise HTTPException(status_code=404, detail="完整方案尚未生成")
    return {"content": content, "filename": f"collab_{task_id}.md"}


# ============================================================
# 发起协作:创建 -> LLM 拆解 -> 后台并行执行 -> 汇总冲突标注
# ============================================================

class TaskCreate(BaseModel):
    """发起协作任务请求"""
    title: str
    description: str = ""
    initiator: str = "用户"
    deadline_minutes: int = 30
    tags: list[str] = []


# 后台执行任务集合(持引用防 GC 提前回收)
_RUNNING: set[asyncio.Task] = set()


@router.post("")
async def create_task(req: TaskCreate, db: AsyncSession = Depends(get_db)):
    """
    发起协作任务:
    1. LLM 把任务拆解为跨领域子任务并指派员工
    2. 落库 TaskCard + TaskAssignment(状态 analyzing)
    3. 后台并行执行(员工 Agent ReAct 循环),完成后 LLM 汇总并显式标注冲突
    """
    title = req.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="任务标题不能为空")

    # 盘点可用员工(在线/试用)
    agents = (await db.execute(
        select(Agent).where(Agent.status.in_(["online", "trial"]))
    )).scalars().all()
    if not agents:
        raise HTTPException(status_code=400, detail="当前无可用员工,无法发起协作")

    depts = (await db.execute(select(Department))).scalars().all()
    domains = (await db.execute(select(Domain))).scalars().all()
    dept_map = {d.id: d.name for d in depts}
    domain_map = {d.id: d.name for d in domains}

    # LLM 拆解(结构化输出,失败重试一次)
    subtasks = await _decompose_task(title, req.description, agents, dept_map, domain_map)
    if not subtasks:
        raise HTTPException(status_code=500, detail="LLM 任务拆解失败,请调整任务描述后重试")

    # 落库任务卡与子任务(立即 commit:后台执行与前端轮询依赖数据可见性)
    agent_map = {a.id: a for a in agents}
    tags = req.tags or sorted({
        domain_map.get(agent_map[s["agent_id"]].domain_id, "")
        for s in subtasks if s["agent_id"] in agent_map
    } - {""})
    card = TaskCard(
        id=uuid.uuid4().hex,
        title=title,
        description=req.description,
        state="in_progress",
        initiator=req.initiator,
        deadline_minutes=req.deadline_minutes,
        tags=tags,
    )
    db.add(card)
    for st in subtasks:
        agent = agent_map[st["agent_id"]]
        db.add(TaskAssignment(
            id=uuid.uuid4().hex,
            task_card_id=card.id,
            agent_id=agent.id,
            agent_name=agent.name,
            agent_emoji=agent.emoji or "🧑‍💻",
            department=dept_map.get(agent.department_id, ""),
            domain=domain_map.get(agent.domain_id, ""),
            subtask_title=st["title"],
            subtask_detail=st["detail"],
            status="analyzing",
            confidence=st["confidence"],
        ))
    await db.commit()

    # 后台并行执行(独立 DB 会话,不占请求连接)
    bg = asyncio.create_task(_execute_task_card(card.id))
    _RUNNING.add(bg)
    bg.add_done_callback(_RUNNING.discard)

    result = await db.execute(
        select(TaskCard).options(selectinload(TaskCard.assignments)).where(TaskCard.id == card.id)
    )
    return _task_to_dict(result.scalar_one())


async def _decompose_task(
    title: str,
    description: str,
    agents: list[Agent],
    dept_map: dict[str, str],
    domain_map: dict[str, str],
) -> list[dict]:
    """
    LLM 拆解协作任务为跨领域子任务
    返回 [{agent_id, title, detail, confidence}],失败返回 []
    """
    from backend.services.llm import chat_completion
    from backend.services.skill_validator import extract_llm_json

    agent_list = [{
        "id": a.id,
        "name": a.name,
        "title": a.title,
        "department": dept_map.get(a.department_id, ""),
        "domain": domain_map.get(a.domain_id, ""),
        "description": (a.description or "")[:80],
    } for a in agents]

    prompt = f"""你是 Agent 办公室的协作任务拆解员。把一个跨领域协作任务拆解为若干子任务,并指派给最合适的员工并行执行。

## 可用员工列表
{json.dumps(agent_list, ensure_ascii=False, indent=2)}

## 协作任务
标题:{title}
描述:{description or "(无补充描述)"}

## 输出要求
返回 JSON(不要输出其他内容):
{{"subtasks": [{{"agent_id": "员工ID", "title": "子任务标题", "detail": "子任务具体要求,说明该员工需要交付什么", "confidence": "HIGH/MEDIUM/LOW"}}]}}

拆解原则:
1. 按专业领域拆分,每个子任务指派给领域最匹配的员工
2. 子任务之间可并行、不互相依赖
3. 同一员工可被指派多个不同角度的子任务,但尽量避免
4. 子任务数量 2~5 个,覆盖任务的主要方面
5. confidence 表示你对该指派的置信度"""

    # GLM 为推理模型,思考耗 token,预算给足;空返回重试一次兜底
    result = ""
    for _ in range(2):
        result = await chat_completion([{"role": "user", "content": prompt}], temperature=0.2, max_tokens=4000)
        if result and result.strip():
            break
        print("[tasks] LLM 拆解返回空,重试")

    data = extract_llm_json(result) if result else None
    if not data:
        print(f"[tasks] LLM 拆解输出非 JSON: {(result or '')[:200]!r}")
        return []

    valid_ids = {a.id for a in agents}
    subtasks = []
    for st in data.get("subtasks", []):
        if st.get("agent_id") in valid_ids and st.get("title"):
            conf = st.get("confidence")
            subtasks.append({
                "agent_id": st["agent_id"],
                "title": str(st["title"])[:200],
                "detail": str(st.get("detail", "")),
                "confidence": conf if conf in ("HIGH", "MEDIUM", "LOW") else "MEDIUM",
            })
    return subtasks[:5]


async def _execute_task_card(task_id: str) -> None:
    """
    后台执行协作任务（两轮讨论模式）:
    第 1 轮各员工并行产出草案 -> 第 2 轮互相可见草案并站在本岗位互评 -> 合成一份完整方案 md -> LLM 汇总冲突标注
    deadline 拆分: 第 1 轮 55%、第 2 轮 35%、合成+汇总保底 90s
    全程使用独立 DB 会话(请求会话已随响应关闭)
    """
    try:
        async with async_session() as db:
            result = await db.execute(
                select(TaskCard).options(selectinload(TaskCard.assignments)).where(TaskCard.id == task_id)
            )
            card = result.scalar_one_or_none()
            if not card:
                return
            deadline_sec = max(card.deadline_minutes, 1) * 60
            assignment_ids = [a.id for a in card.assignments]
            title, desc = card.title, card.description

        # 分阶段预算: 合成+汇总保底 90s, 剩余按 55%/35% 切给两轮
        reserve_sec = min(90, deadline_sec * 0.1)
        budget1 = (deadline_sec - reserve_sec) * 0.55
        budget2 = (deadline_sec - reserve_sec) * 0.35

        # ---- 第 1 轮: 并行产出草案 ----
        try:
            await asyncio.wait_for(
                asyncio.gather(*[_run_subtask(aid, title, desc) for aid in assignment_ids]),
                timeout=budget1,
            )
        except asyncio.TimeoutError:
            print(f"[tasks] 任务 {task_id} 第 1 轮(草案)超过 {budget1:.0f}s 预算")
            # 超时兜底:未交付的子任务标记为待澄清
            async with async_session() as db:
                rows = (await db.execute(
                    select(TaskAssignment).where(
                        TaskAssignment.task_card_id == task_id,
                        TaskAssignment.status == "analyzing",
                    )
                )).scalars().all()
                for r in rows:
                    r.status = "clarify"
                    r.subtask_detail = "执行超时,未能按期交付,请人工跟进或重新发起。"
                await db.commit()

        # ---- 第 2 轮: 互评(仅对已交付草案的子任务; 不足 2 份草案则跳过直接合成) ----
        async with async_session() as db:
            drafts = (await db.execute(
                select(TaskAssignment).where(
                    TaskAssignment.task_card_id == task_id,
                    TaskAssignment.status == "submitted",
                )
            )).scalars().all()
            draft_payload = [{
                "assignment_id": d.id,
                "agent_name": d.agent_name,
                "domain": d.domain,
                "subtask_title": d.subtask_title,
                "draft": d.subtask_detail or "",
            } for d in drafts]
            draft_ids = [d.id for d in drafts]

        if len(draft_ids) >= 2:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*[_run_discussion(aid, title, desc, draft_payload) for aid in draft_ids]),
                    timeout=budget2,
                )
            except asyncio.TimeoutError:
                print(f"[tasks] 任务 {task_id} 第 2 轮(互评)超过 {budget2:.0f}s 预算")
                # 超时兜底:互评中的子任务回退为 submitted(草案保留,绝不覆写 subtask_detail)
                async with async_session() as db:
                    rows = (await db.execute(
                        select(TaskAssignment).where(
                            TaskAssignment.task_card_id == task_id,
                            TaskAssignment.status == "discussing",
                        )
                    )).scalars().all()
                    for r in rows:
                        r.status = "submitted"
                    await db.commit()
        else:
            print(f"[tasks] 任务 {task_id} 有效草案不足 2 份,跳过互评直接合成")

        # ---- 合成完整方案 + 汇总(无论是否超时,基于已交付的产出) ----
        async with async_session() as db:
            result = await db.execute(
                select(TaskCard).options(selectinload(TaskCard.assignments)).where(TaskCard.id == task_id)
            )
            card = result.scalar_one()

            # 合成完整方案 md 并落盘(失败则用代码拼接兜底,保证方案一定存在)
            from backend.services.file_service import write_collab_doc
            doc_failed = False
            try:
                doc_md = await _synthesize_doc(card)
                if not doc_md:
                    doc_md = _fallback_doc(card)
                card.result_doc_path = write_collab_doc(card.id, doc_md)
            except Exception as e:
                doc_failed = True
                print(f"[tasks] 任务 {task_id} 方案合成/落盘失败: {e}")

            card.conflict_note = await _summarize(card)
            if doc_failed and card.conflict_note.startswith("✅"):
                card.conflict_note = "⚠️" + card.conflict_note[1:] + "\n\n(完整方案落盘失败,请查看各员工交付内容)"
            card.state = "completed"
            await db.commit()
    except Exception as e:
        print(f"[tasks] 任务 {task_id} 执行异常: {e}")
        try:
            async with async_session() as db:
                card = (await db.execute(
                    select(TaskCard).where(TaskCard.id == task_id)
                )).scalar_one_or_none()
                if card:
                    card.state = "completed"
                    card.conflict_note = f"⚠️ 执行过程异常:{e}"
                    await db.commit()
        except Exception:
            pass


async def _run_agent_question(
    agent: Agent,
    question: str,
    db: AsyncSession,
    *,
    session_id: str,
    dept_name: str,
    domain_name: str,
) -> str:
    """
    复用员工 Agent 执行链回答一个问题(岗位包 + 工具白名单 + ReAct 循环,非流式)
    两轮讨论共用:仅 question 与 session_id 不同;session_id 独立保证不注入聊天历史
    返回最终文本;异常向上抛出由调用方处理
    """
    from backend.routers.frontdesk import _load_role_pack_spec
    from backend.runtime.context import build_context
    from backend.runtime.tools import build_tool_registry
    from backend.runtime.mcp_client import load_mcp_tools
    from backend.runtime.runner import AgentRunner

    role_pack_spec = await _load_role_pack_spec(agent, db)
    context = await build_context(
        agent=agent,
        session_id=session_id,
        db=db,
        role_pack_spec=role_pack_spec,
        dept_name=dept_name,
        domain_name=domain_name,
    )
    tool_registry = build_tool_registry(
        context.allowed_tools,
        allowed_repos=context.allowed_repos,
        default_repo=context.default_repo,
        default_domain=domain_name,
    )
    # MCP 工具会话生命周期须覆盖整个执行过程
    async with AsyncExitStack() as mcp_stack:
        for mcp_tool in await load_mcp_tools(mcp_stack, context.allowed_tools, db):
            tool_registry.register(mcp_tool)
        runner = AgentRunner()
        result = await runner.execute(question, context, tool_registry, db=db)
    return result.final_content or "(无输出)"


# LLM 失败标记:provider 把调用异常转为错误内容返回(不抛异常),需据此判定重试
_LLM_FAIL_MARKERS = ("[LLM 调用失败", "[LLM 重试耗尽]")


async def _run_agent_question_with_retry(
    agent: Agent,
    question: str,
    db: AsyncSession,
    *,
    session_id: str,
    dept_name: str,
    domain_name: str,
    max_retries: int = 2,
) -> str:
    """
    带重试的员工问答包装(第 7 轮需求:保证协作会议室每个人都输出)
    provider 已做瞬时错误退避,此处再做整轮重试兜底:
    - 返回内容命中 LLM 失败标记 / 空输出 → 整轮重试(最多 max_retries 次,退避 3s/8s)
    - CancelledError(超时取消)直接上抛,不参与重试
    """
    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            content = await _run_agent_question(
                agent, question, db,
                session_id=session_id,
                dept_name=dept_name,
                domain_name=domain_name,
            )
            # 命中失败标记或实质空输出 → 视为本轮失败,进入重试
            if any(m in content for m in _LLM_FAIL_MARKERS) or content.strip() in ("", "(无输出)"):
                raise RuntimeError(f"LLM 输出无效: {content[:80]}")
            return content
        except asyncio.CancelledError:
            raise  # 超时取消由上层统一处理,不重试
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                wait = 3 if attempt == 0 else 8
                print(f"[tasks] 员工 {agent.name} 第 {attempt + 1} 轮输出失败({e}),{wait}s 后重试")
                await asyncio.sleep(wait)
    # 重试耗尽:抛出最后一次异常,由调用方走兜底(标记 clarify / 回退 submitted)
    raise last_err if last_err else RuntimeError("LLM 重试耗尽")


async def _run_subtask(assignment_id: str, task_title: str, task_desc: str) -> None:
    """
    第 1 轮:执行单个子任务产出草案
    完成后把草案内容写回 subtask_detail,状态 analyzing -> submitted
    """
    async with async_session() as db:
        assignment = (await db.execute(
            select(TaskAssignment).where(TaskAssignment.id == assignment_id)
        )).scalar_one_or_none()
        if not assignment:
            return
        agent = (await db.execute(
            select(Agent).where(Agent.id == assignment.agent_id)
        )).scalar_one_or_none()
        if not agent:
            assignment.status = "clarify"
            assignment.subtask_detail = "指派的员工不存在或已离职,请人工处理。"
            await db.commit()
            return

        question = (
            f"【协作任务】{task_title}\n"
            f"任务背景:{task_desc or '无'}\n\n"
            f"分配给你的子任务:{assignment.subtask_title}\n"
            f"具体要求:{assignment.subtask_detail}\n\n"
            "请基于你的专业能力完成该子任务,交付完整、详实的成果内容(背景分析 + 结论 + 具体方案/细节,可使用工具查询真实数据)。"
        )

        try:
            content = await _run_agent_question_with_retry(
                agent, question, db,
                session_id=f"task-{assignment_id}",  # 独立会话标识,不注入聊天历史
                dept_name=assignment.department,
                domain_name=assignment.domain,
            )
            assignment.subtask_detail = content
            assignment.status = "submitted"
        except asyncio.CancelledError:
            raise  # 超时取消由上层统一标记,不参与兜底
        except Exception as e:
            assignment.status = "clarify"
            assignment.subtask_detail = f"执行失败:{e}"
        await db.commit()


async def _run_discussion(
    assignment_id: str,
    task_title: str,
    task_desc: str,
    drafts: list[dict],
) -> None:
    """
    第 2 轮:互评——员工可见所有草案,站在自己岗位能力上分析、补充、质疑、完善
    互评内容写入 discussion_note,状态 submitted -> discussing -> discussed
    失败时状态回退 submitted(草案保留,绝不覆写 subtask_detail)
    """
    async with async_session() as db:
        assignment = (await db.execute(
            select(TaskAssignment).where(TaskAssignment.id == assignment_id)
        )).scalar_one_or_none()
        if not assignment:
            return
        agent = (await db.execute(
            select(Agent).where(Agent.id == assignment.agent_id)
        )).scalar_one_or_none()
        if not agent:
            return

        # 先置 discussing 并 commit,让前端轮询立刻看到"讨论中"
        assignment.status = "discussing"
        await db.commit()

        # 拼装所有草案(含自己的,标注作者/领域;单份截断防 prompt 膨胀)
        draft_blocks = []
        for d in drafts:
            own = "(你的草案)" if d["assignment_id"] == assignment_id else ""
            draft_blocks.append(
                f"### {d['agent_name']}({d['domain']}){own} - {d['subtask_title']}\n{(d['draft'] or '(无内容)')[:6000]}"
            )
        drafts_text = "\n\n".join(draft_blocks)

        question = (
            f"【协作任务·讨论环节】{task_title}\n"
            f"任务背景:{task_desc or '无'}\n\n"
            f"以下是各位同事(含你)针对该任务不同子任务产出的草案:\n\n{drafts_text}\n\n"
            "请站在你的岗位能力和专业领域上,参与讨论:\n"
            "1. 对其他同事的草案进行分析——指出亮点、疏漏、与你专业领域的冲突或衔接点;\n"
            "2. 从你自己的专业角度补充关键内容(数据、方案细节、风险提示),可使用工具查询真实数据佐证;\n"
            "3. 如有不同意见,明确提出质疑并给出你的理由和替代建议;\n"
            "4. 如发现自己草案有需要修正/完善之处,一并给出修订内容。\n"
            "要求:内容详尽、具体、有论据,不要泛泛而谈。"
        )

        try:
            content = await _run_agent_question_with_retry(
                agent, question, db,
                session_id=f"task-{assignment_id}-r2",  # 第 2 轮独立会话,互评上下文全部塞在 question 里
                dept_name=assignment.department,
                domain_name=assignment.domain,
            )
            assignment.discussion_note = content
            assignment.status = "discussed"
        except asyncio.CancelledError:
            raise  # 超时取消由上层统一回退状态,不参与兜底
        except Exception as e:
            print(f"[tasks] 子任务 {assignment_id} 互评失败: {e}")
            assignment.status = "submitted"  # 草案保留,互评留空,不阻塞他人
        await db.commit()


async def _synthesize_doc(card: TaskCard) -> Optional[str]:
    """
    LLM 合成完整方案 md:基于各员工的草案 + 互评,产出一份可落地的完整方案
    单份输入截断 6000 字符护栏;空返重试一次;失败返回 None(调用方用代码拼接兜底)
    """
    from backend.services.llm import chat_completion

    parts = []
    for s in card.assignments:
        draft = (s.subtask_detail or "").strip()
        # 仍在分析中/拆解指令未覆写的视为无草案
        if s.status == "analyzing":
            draft = ""
        parts.append(
            f"### {s.agent_name}({s.department}/{s.domain})- {s.subtask_title}\n"
            f"**草案**:\n{draft[:6000] if draft else '(未交付)'}\n\n"
            f"**互评与补充**:\n{(s.discussion_note or '').strip()[:6000] if (s.discussion_note or '').strip() else '(无互评)'}"
        )
    joined = "\n\n".join(parts)

    prompt = f"""你是协作会议室的汇总员。多位员工围绕一个协作任务,先各自产出草案,再互相可见草案后站在各自岗位上进行了互评与补充。现在请你综合全部草案与互评,合成一份完整、可落地的方案文档(Markdown)。

## 协作任务
标题:{card.title}
描述:{card.description or '(无补充描述)'}

## 各员工的草案与互评
{joined}

## 输出要求(直接输出 Markdown 正文,不要输出其他说明)
按以下章节组织:
1. **任务背景与目标**——用一段话说明任务要解决什么问题、达成什么目标
2. **总体方案**——按专业领域分节,每节落到:结论、具体做法、依据(引用员工草案/互评中的数据与论据)
3. **各部门要点与衔接**——各领域交付物之间的依赖与衔接关系,谁配合谁、在什么节点
4. **分歧点与裁决**——互评中出现的不同意见逐条列出,给出采纳/否决的结论与理由(不要和稀泥)
5. **风险与待确认**——执行风险、数据缺口、需要人工确认的开放问题
6. **行动清单与分工**——可执行的下一步动作,每条注明负责领域

要求:内容详尽、完整、可落地,充分吸收互评环节达成的共识与补充;Markdown 层级清晰,标题使用 ##/###"""

    try:
        result = ""
        for _ in range(2):
            result = await chat_completion([{"role": "user", "content": prompt}], temperature=0.3, max_tokens=16000)
            if result and result.strip():
                break
            print(f"[tasks] 任务 {card.id} 方案合成返回空,重试")
        if result and result.strip():
            return f"# {card.title} - 协作方案\n\n{result.strip()}\n"
    except Exception as e:
        print(f"[tasks] 任务 {card.id} 方案合成失败: {e}")
    return None


def _fallback_doc(card: TaskCard) -> str:
    """
    代码拼接兜底方案(LLM 合成失败时保证 md 一定存在):标题 + 各员工草案/互评原文罗列
    """
    lines = [
        f"# {card.title} - 协作方案(汇编)",
        "",
        f"> 任务描述:{card.description or '(无)'}",
        "> 注:LLM 合成失败,以下为各员工草案与互评原文汇编。",
        "",
    ]
    for s in card.assignments:
        lines.append(f"## {s.agent_name}({s.department}/{s.domain})- {s.subtask_title}")
        lines.append("")
        lines.append("### 草案")
        lines.append((s.subtask_detail or "").strip() if s.status != "analyzing" else "(未交付)")
        lines.append("")
        if (s.discussion_note or "").strip():
            lines.append("### 互评与补充")
            lines.append(s.discussion_note.strip())
            lines.append("")
    return "\n".join(lines)


async def _summarize(card: TaskCard) -> str:
    """
    LLM 汇总各子任务产出,显式标注冲突(不强行合并)
    首行以 ✅(无冲突)或 ⚠️(有冲突/异常)开头,前端据此渲染冲突类型
    """
    from backend.services.llm import chat_completion

    parts = []
    has_failure = False
    for s in card.assignments:
        # submitted(有草案)与 discussed(草案+互评)都算成功交付
        if s.status not in ("submitted", "discussed"):
            has_failure = True
        parts.append(
            f"### {s.agent_name}({s.department}/{s.domain})- {s.subtask_title}\n{s.subtask_detail or '(无产出)'}"
        )
    joined = "\n\n".join(parts)

    prompt = f"""你是协作会议室的汇总员。多个员工并行完成了一个协作任务的不同子任务,请汇总他们的产出。

## 协作任务
{card.title}
{card.description or ''}

## 各员工交付内容
{joined}

## 输出要求
1. 第一行必须以 ✅ 或 ⚠️ 开头:产出之间无矛盾用 ✅;存在观点/方案冲突,或有子任务未成功交付用 ⚠️
2. 之后给出整体汇总(200 字内),**冲突必须显式标注、逐条列出,不要强行合并或和稀泥**
3. 用简洁专业的中文"""

    try:
        # 汇总属结构化场景,预算给足;空返重试一次
        result = ""
        for _ in range(2):
            result = await chat_completion([{"role": "user", "content": prompt}], temperature=0.2, max_tokens=3000)
            if result and result.strip():
                break
        if result and result.strip():
            note = result.strip()
            if has_failure and note.startswith("✅"):
                note = "⚠️" + note[1:]
            return note
    except Exception as e:
        print(f"[tasks] 汇总失败: {e}")
    prefix = "⚠️ " if has_failure else "✅ "
    return prefix + "各子任务已执行完毕,LLM 汇总失败,请直接查看各员工交付内容。"


def _task_to_dict(t: TaskCard) -> dict:
    """将 TaskCard ORM 转为 API 响应"""
    tags = t.tags or []
    return {
        "id": t.id,
        "title": t.title,
        "description": t.description or "",
        "status": t.state,
        "meta_dept": t.initiator or "",
        "meta_tag": " · ".join(tags) if tags else "",
        "meta_overtime": f"超时 {t.deadline_minutes} 分钟",
        "subtasks": [
            {
                "id": s.id,
                "agent_id": s.agent_id,
                "agent_name": s.agent_name,
                "agent_emoji": s.agent_emoji,
                "department_id": s.department or "",
                "domain_name": s.domain or "",
                "status": s.status,
                "title": s.subtask_title,
                "detail": s.subtask_detail or "",
                "discussion": s.discussion_note or "",
                "confidence": s.confidence,
            }
            for s in (t.assignments or [])
        ],
        "conflict_note": t.conflict_note or "",
        "conflict_type": _conflict_type(t.conflict_note),
        "doc_available": bool(t.result_doc_path),
    }
