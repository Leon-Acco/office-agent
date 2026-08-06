"""
Subagent Manager - 借鉴 nanobot agent/subagent.py
实现"总台 -> 领域员工"的多 Agent 协作

关键设计（借鉴 nanobot）：
1. asyncio.Task 后台执行子任务
2. 每个子任务用独立 AgentRunner（隔离工具白名单）
3. 结果回注主会话（作为 system 消息注入）
4. max_concurrent 限制并发数

业务绑定：
- 总台判断问题需要跨域协作
- 创建子任务分配给不同领域员工
- 子任务结果汇总后由总台生成最终回答
"""
import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.agent import Agent
from backend.models.company import Department, Domain
from backend.runtime.runner import AgentRunner, AgentRunResult
from backend.runtime.context import build_context, AgentContext
from backend.runtime.tools import build_tool_registry


@dataclass
class SubagentTask:
    """子任务定义"""
    task_id: str
    agent: Agent              # 执行子任务的员工
    question: str             # 子问题
    dept_name: str = ""
    domain_name: str = ""
    result: str = ""          # 执行结果
    error: str = ""           # 错误信息
    status: str = "pending"   # pending / running / done / error


@dataclass
class SubagentStatus:
    """子任务状态（借鉴 nanobot SubagentStatus）"""
    task_id: str
    label: str
    task_description: str
    started_at: float
    phase: str = "initializing"  # initializing / running / done / error
    error: str = ""


class SubagentManager:
    """
    子代理管理器（借鉴 nanobot SubagentManager）
    管理多个领域员工并行执行子任务
    """

    def __init__(self, max_concurrent: int = 3):
        self.max_concurrent = max_concurrent
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._results: dict[str, SubagentTask] = {}

    async def spawn(
        self,
        agent: Agent,
        question: str,
        db: AsyncSession,
        dept_name: str = "",
        domain_name: str = "",
        role_pack_spec: dict | None = None,
    ) -> str:
        """
        启动子任务（借鉴 nanobot spawn）
        返回 task_id，不阻塞
        """
        task_id = uuid.uuid4().hex[:8]

        # 检查并发限制
        if len(self._running_tasks) >= self.max_concurrent:
            # 等待一个任务完成
            done, pending = await asyncio.wait(
                self._running_tasks.values(),
                return_when=asyncio.FIRST_COMPLETED,
            )

        sub_task = SubagentTask(
            task_id=task_id,
            agent=agent,
            question=question,
            dept_name=dept_name,
            domain_name=domain_name,
            status="running",
        )
        self._results[task_id] = sub_task

        # 创建后台任务
        bg_task = asyncio.create_task(
            self._run_subagent(task_id, agent, question, db, dept_name, domain_name, role_pack_spec)
        )
        self._running_tasks[task_id] = bg_task

        return task_id

    async def _run_subagent(
        self,
        task_id: str,
        agent: Agent,
        question: str,
        db: AsyncSession,
        dept_name: str,
        domain_name: str,
        role_pack_spec: dict | None,
    ) -> None:
        """
        执行子任务（借鉴 nanobot _run_subagent）
        用独立 AgentRunner 执行，结果存入 _results
        """
        try:
            # 构建隔离的上下文 + 工具注册表
            spec = role_pack_spec or {
                "tools": ["searchKnowledge", "getEmployeeInfo", "searchResource"],
                "skills": [],
                "resources": agent.resources or [],
                "permission": {
                    "read_only": True,
                    "acl_mode": "whitelist",
                    "budget": {"steps": 5, "calls": 3, "timeout": 30, "token": 24000},
                },
            }

            context = await build_context(
                agent=agent,
                session_id=f"subagent_{task_id}",
                db=db,
                role_pack_spec=spec,
                dept_name=dept_name,
                domain_name=domain_name,
                history_limit=0,  # 子任务不带历史
            )

            tool_registry = build_tool_registry(context.allowed_tools)
            runner = AgentRunner()

            # 执行（非流式，子任务不需要流式输出）
            result = await runner.execute(question, context, tool_registry, db=db)

            self._results[task_id].result = result.final_content
            self._results[task_id].status = "done"

        except Exception as e:
            self._results[task_id].error = str(e)
            self._results[task_id].status = "error"
            print(f"[Subagent] 任务 {task_id} 失败: {e}")

        finally:
            self._running_tasks.pop(task_id, None)

    async def wait_all(self, timeout: float = 60.0) -> dict[str, SubagentTask]:
        """
        等待所有子任务完成（借鉴 nanobot 的结果收集）
        返回所有任务结果
        """
        if self._running_tasks:
            try:
                await asyncio.wait(
                    list(self._running_tasks.values()),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                print(f"[Subagent] 等待超时（{timeout}s），仍有 {len(self._running_tasks)} 个任务未完成")

        return dict(self._results)

    def get_results_summary(self) -> str:
        """
        汇总所有子任务结果（用于注入主会话）
        借鉴 nanobot 的 subagent_result 回注
        """
        if not self._results:
            return ""

        lines = []
        for task_id, task in self._results.items():
            if task.status == "done" and task.result:
                lines.append(f"### {task.agent.name}（{task.domain_name}）的回答：\n{task.result}\n")
            elif task.status == "error":
                lines.append(f"### {task.agent.name}（{task.domain_name}）：执行失败 - {task.error}\n")

        return "\n".join(lines) if lines else ""

    def clear(self) -> None:
        """清理所有任务"""
        for task in self._running_tasks.values():
            task.cancel()
        self._running_tasks.clear()
        self._results.clear()
