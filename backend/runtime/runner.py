"""
AgentRunner - 借鉴 nanobot agent/runner.py
适配 Office_Agent：绑定岗位包能力边界 + 预算追踪 + SSE 流式输出

核心循环（借鉴 nanobot AgentRunner.run）：
  for iteration in range(max_iterations):
      1. 调用 Provider（带工具定义）
      2. 如果有 tool_calls -> 执行工具 -> 结果回填 -> continue
      3. 否则产出终答 -> 结束

关键健壮性设计（借鉴 nanobot）：
1. 迭代上限：max_iterations 防止无限循环
2. 预算耗尽兜底：finalize_on_max_iterations
3. 畸形 tool_call 清洗：在写入历史前丢弃（在 Provider 层处理）
4. 空响应恢复：重试 2 次
5. 工具执行错误转为 ToolResult.error（不抛异常）
"""
import json
import re
import asyncio
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable

from backend.runtime.provider import LLMProvider, LLMResponse, ToolCallRequest
from backend.runtime.context import AgentContext, Budget, build_system_prompt
from backend.runtime.tool_registry import ToolRegistry
from backend.runtime.tool_base import ToolResult
from backend.runtime.hooks import AgentHook, AgentHookContext, ToolEvent, AuditHook, SecurityHook
from backend.runtime.consolidator import Consolidator, estimate_messages_tokens
from backend.services.llm import LLM_BASE_URL, LLM_API_KEY, LLM_MODEL


# 同一标识符连续重复 >=6 次(如 "getCodeExcerpt getCodeExcerpt ..."):
# GLM 在预算耗尽兜底轮(tools=None)仍想调工具时,会把工具名当正文复读刷屏,
# 实测事故现场为「两段正常中文 + 工具名复读数百次」(协作草案刷屏 bug)
# 仅匹配标识符形 token(字母/下划线开头),排除 │、─ 等制表符,避免误伤 ASCII 架构图/空单元格表格
_TOOL_NAME_SPAM_RE = re.compile(r"([A-Za-z_][\w.-]*)(?:\s+\1){5,}")


def _strip_tool_name_spam(text: str) -> str:
    """
    截断模型退化产生的工具名刷屏(同一标识符连续重复 >=6 次)
    保留刷屏点之前的正常内容;纯刷屏返回空串,由上层空输出重试兜底
    """
    if not text:
        return text
    m = _TOOL_NAME_SPAM_RE.search(text)
    if not m:
        return text
    return text[:m.start()].rstrip()


@dataclass
class AgentRunResult:
    """
    执行结果（借鉴 nanobot AgentRunResult）
    """
    final_content: str
    messages: list[dict] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    stop_reason: str = "completed"  # completed / max_iterations / budget_exhausted / error
    iterations: int = 0
    tool_events: list[dict] = field(default_factory=list)


class AgentRunner:
    """
    Agent 执行器（借鉴 nanobot AgentRunner）
    驱动 LLM ⇄ Tool 的 ReAct 循环
    """

    # 健壮性常量（借鉴 nanobot）
    _MAX_EMPTY_RETRIES = 2          # 空响应重试
    _MAX_FINALIZE_RETRIES = 1       # 预算耗尽后的收尾调用

    def __init__(self, provider: LLMProvider | None = None, hooks: list[AgentHook] | None = None,
                 consolidator: Consolidator | None = None):
        self.provider = provider or LLMProvider(
            base_url=LLM_BASE_URL,
            api_key=LLM_API_KEY,
            model=LLM_MODEL,
        )
        self.hooks = hooks or []
        self.consolidator = consolidator or Consolidator(max_tokens=32000)

    def _build_hook_context(self, iteration: int, tool_calls: list[ToolCallRequest] = None,
                            tool_events: list[ToolEvent] = None) -> AgentHookContext:
        """构建 Hook 上下文"""
        return AgentHookContext(
            iteration=iteration,
            tool_calls=tool_calls or [],
            tool_events=tool_events or [],
        )

    async def _run_hooks(self, method: str, hook_ctx: AgentHookContext) -> None:
        """执行所有 Hook 的指定方法"""
        for hook in self.hooks:
            try:
                fn = getattr(hook, method)
                await fn(hook_ctx)
            except Exception as e:
                print(f"[hook] {method} failed: {e}")

    async def execute(
        self,
        question: str,
        context: AgentContext,
        tool_registry: ToolRegistry,
        db=None,
    ) -> AgentRunResult:
        """
        执行 Agent ReAct 循环（非流式）

        参数：
            question: 用户问题
            context: Agent 上下文（含历史 + 预算）
            tool_registry: 工具注册表（从岗位包白名单构建）
            db: 数据库会话（传给工具执行）
        """
        # 构建初始消息
        system_prompt = build_system_prompt(context)
        messages = [{"role": "system", "content": system_prompt}]

        # 注入历史（短期记忆）
        for h in context.history:
            messages.append(h)

        # 当前问题
        messages.append({"role": "user", "content": question})

        # 工具定义
        tools = tool_registry.get_definitions()

        tools_used = []
        tool_events = []

        for iteration in range(context.budget.max_steps):
            context.budget.consume_step()

            # 调用 LLM
            response = await self.provider.chat(messages, tools=tools)

            # 空响应恢复（借鉴 nanobot _MAX_EMPTY_RETRIES）
            if not response.content and not response.tool_calls:
                if iteration < self._MAX_EMPTY_RETRIES:
                    messages.append({"role": "user", "content": "请继续回答。"})
                    continue
                else:
                    break

            # 有工具调用 -> 执行 -> 回填 -> 继续
            if response.has_tool_calls:
                # 先把 assistant 消息加入历史
                messages.append({
                    "role": "assistant",
                    "content": response.content or "",
                    "tool_calls": [
                        {"id": tc.id, "type": "function",
                         "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                        for tc in response.tool_calls
                    ],
                })

                # 逐个执行工具
                for tc in response.tool_calls:
                    if not context.budget.can_continue():
                        break
                    context.budget.consume_call()

                    # 执行工具
                    result = await self._execute_tool(tc, tool_registry, db)

                    tools_used.append(tc.name)
                    tool_events.append({
                        "name": tc.name,
                        "arguments": tc.arguments,
                        "result_preview": str(result)[:200],
                        "is_error": result.is_error,
                    })

                    # 工具结果回填（OpenAI 格式：role=tool）
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": str(result),
                    })

                # 继续下一轮迭代（让 LLM 看到工具结果后决定下一步）
                continue

            # 终答(清洗工具名刷屏;纯刷屏清洗后为空,由上层空输出重试兜底)
            return AgentRunResult(
                final_content=_strip_tool_name_spam(response.content),
                messages=messages,
                tools_used=tools_used,
                stop_reason="completed",
                iterations=iteration + 1,
                tool_events=tool_events,
            )

        # 预算耗尽兜底（借鉴 nanobot finalize_on_max_iterations）
        # 做一次无工具的收尾调用，给用户一个回答（8000:GLM 推理模型的思考链与正文共享预算,4000 易被思考吃光）
        # 明确禁止罗列工具名:tools=None 时模型仍想调工具,会把工具名当正文复读刷屏
        messages.append({
            "role": "user",
            "content": "请基于已收集的信息，给出完整、详细的最终回答（结论 + 依据 + 展开说明）。"
                       "禁止输出或重复任何工具名称、调用计划，直接写最终结论。",
        })
        final = await self.provider.chat(messages, tools=None, max_tokens=8000)
        final_content = _strip_tool_name_spam(final.content or "")

        # 清洗后所剩无几(响应主体就是刷屏):换更强指令重试一次,取更好的一份
        if len(final_content) < 200 and final_content != (final.content or ""):
            messages.append({
                "role": "user",
                "content": "你的上一次输出退化成了工具名重复。请忘掉工具调用,直接基于已有信息写一份完整的文字结论。",
            })
            retry = await self.provider.chat(messages, tools=None, max_tokens=8000)
            retry_content = _strip_tool_name_spam(retry.content or "")
            if len(retry_content) > len(final_content):
                final_content = retry_content

        return AgentRunResult(
            final_content=final_content or "抱歉，我在处理过程中超出了预算限制。请尝试简化问题。",
            messages=messages,
            tools_used=tools_used,
            stop_reason="budget_exhausted",
            iterations=context.budget.max_steps,
            tool_events=tool_events,
        )

    async def execute_stream(
        self,
        question: str,
        context: AgentContext,
        tool_registry: ToolRegistry,
        db=None,
    ) -> AsyncIterator[dict]:
        """
        流式执行 Agent ReAct 循环

        yield 事件格式：
            {"type": "thinking"}                              # 每轮 LLM 调用前:思考占位(GLM 推理期无正文输出)
            {"type": "tool.start", "name": "searchKnowledge", "arguments": {...}}
            {"type": "tool.result", "name": "searchKnowledge", "result": "..."}
            {"type": "answer.completed", "final_content": "...", "tools_used": [...]}
            {"type": "error", "message": "..."}

        输出节奏(第 8 轮需求):正文不再逐 chunk 下发,思考期只发 thinking 占位,
        终答攒齐后由 answer.completed 一次性输出(一口气给出完整回答);
        中间轮伴随工具调用的过渡文本不上屏(工具叙事已足够表达进度)
        """
        # 构建初始消息
        system_prompt = build_system_prompt(context)
        messages = [{"role": "system", "content": system_prompt}]

        # 注入历史
        for h in context.history:
            messages.append(h)

        # 当前问题
        messages.append({"role": "user", "content": question})

        # 工具定义
        tools = tool_registry.get_definitions()

        tools_used = []

        for iteration in range(context.budget.max_steps):
            context.budget.consume_step()

            try:
                # 上下文压缩（借鉴 nanobot Consolidator）
                if self.consolidator.needs_consolidation(messages):
                    messages = await self.consolidator.consolidate(messages, self.provider)
                    print(f"[Consolidator] 已压缩上下文，当前 {estimate_messages_tokens(messages)} tokens")

                # 流式调用 LLM(思考期先发占位,正文攒缓冲、终答一次性输出)
                yield {"type": "thinking"}
                accumulated_content = ""
                final_response = None

                async for chunk_text, response in self.provider.chat_stream(messages, tools=tools):
                    if chunk_text:
                        accumulated_content += chunk_text
                    if response:
                        final_response = response

                if not final_response:
                    continue

                # 有工具调用
                if final_response.has_tool_calls:
                    # assistant 消息加入历史
                    messages.append({
                        "role": "assistant",
                        "content": final_response.content or "",
                        "tool_calls": [
                            {"id": tc.id, "type": "function",
                             "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                            for tc in final_response.tool_calls
                        ],
                    })

                    # 逐个执行工具
                    iteration_tool_events = []
                    for tc in final_response.tool_calls:
                        if not context.budget.can_continue():
                            break
                        context.budget.consume_call()

                        # beforeTool Hook（参数校验 / 注入防护）
                        pre_ctx = self._build_hook_context(iteration, [tc])
                        await self._run_hooks("before_execute_tools", pre_ctx)

                        # 检查是否被 Hook 阻断
                        if tc.arguments.get("_blocked"):
                            result = ToolResult.error(f"安全阻断: {tc.arguments.get('_reason', '未知')}")
                        else:
                            yield {"type": "tool.start", "name": tc.name, "arguments": tc.arguments}
                            result = await self._execute_tool(tc, tool_registry, db)

                        tools_used.append(tc.name)

                        # 构建 ToolEvent
                        evt = ToolEvent(
                            name=tc.name,
                            arguments=tc.arguments,
                            result=str(result),
                            is_error=result.is_error,
                        )
                        iteration_tool_events.append(evt)

                        yield {"type": "tool.result", "name": tc.name, "result": str(result)[:500], "is_error": result.is_error}

                        # 工具结果回填
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": str(result),
                        })

                    # afterTool Hook（结果脱敏 / 审计）
                    post_ctx = self._build_hook_context(iteration, tool_events=iteration_tool_events)
                    await self._run_hooks("after_execute_tools", post_ctx)

                    # after_iteration Hook（usage 追踪）
                    iter_ctx = self._build_hook_context(iteration, tool_events=iteration_tool_events)
                    await self._run_hooks("after_iteration", iter_ctx)

                    # 继续下一轮（让 LLM 看到工具结果）
                    continue

                # 终答(清洗工具名刷屏后一次性输出)
                yield {
                    "type": "answer.completed",
                    "final_content": _strip_tool_name_spam(accumulated_content),
                    "tools_used": tools_used,
                    "iterations": iteration + 1,
                }
                return

            except Exception as e:
                yield {"type": "error", "message": str(e)}
                return

        # 预算耗尽兜底(禁止罗列工具名:tools=None 时模型会把工具名当正文复读刷屏)
        messages.append({
            "role": "user",
            "content": "请基于已收集的信息，给出完整、详细的最终回答（结论 + 依据 + 展开说明）。"
                       "禁止输出或重复任何工具名称、调用计划，直接写最终结论。",
        })
        try:
            yield {"type": "thinking"}
            fallback_content = ""
            async for chunk_text, response in self.provider.chat_stream(messages, tools=None, max_tokens=8000):
                if chunk_text:
                    fallback_content += chunk_text
                if response and response.is_final:
                    yield {
                        "type": "answer.completed",
                        "final_content": _strip_tool_name_spam(response.content or fallback_content),
                        "tools_used": tools_used,
                        "iterations": context.budget.max_steps,
                    }
                    return
        except Exception as e:
            yield {"type": "error", "message": f"收尾调用失败: {e}"}

    async def _execute_tool(self, tc: ToolCallRequest, registry: ToolRegistry, db=None) -> ToolResult:
        """
        执行单个工具调用
        借鉴 nanobot：错误返回 ToolResult.error 而非抛异常
        """
        # 检查工具是否在白名单内
        tool = registry.get(tc.name)
        if not tool:
            available = registry.get_available_names()
            return ToolResult.error(f"工具 '{tc.name}' 不在可用列表中。可用: {available}")

        # 注入 db（业务工具需要数据库访问）
        try:
            # 检查 execute 方法是否接受 db 参数
            import inspect
            sig = inspect.signature(tool.execute)
            if "db" in sig.parameters and db is not None:
                return await registry.execute(tc.name, {**tc.arguments, "db": db})
            else:
                return await registry.execute(tc.name, tc.arguments)
        except Exception as e:
            return ToolResult.error(f"工具执行异常: {e}")
