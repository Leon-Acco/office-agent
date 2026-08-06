"""
Agent Hooks - 借鉴 nanobot agent/hook.py + turn_hooks.py
在工具执行前后插入钩子：参数校验 / 注入防护 / 审计 / 结果脱敏

设计要点（借鉴 nanobot）：
1. AgentHook 基类：before_execute_tools / after_iteration / after_execute_tools
2. AgentHookContext：传递 tool_calls / tool_events / iteration / usage
3. 子类可选择性覆写，不强制实现所有方法
4. 审计 Hook：把工具调用写入 AuditLog
5. 安全 Hook：参数注入防护 + 结果脱敏
"""
from abc import ABC
from dataclasses import dataclass, field
from typing import Any
from datetime import datetime, timezone

from backend.runtime.provider import ToolCallRequest
from backend.runtime.tool_base import ToolResult


@dataclass
class ToolEvent:
    """单次工具调用事件"""
    name: str
    arguments: dict
    result: str = ""
    is_error: bool = False
    latency_ms: int = 0


@dataclass
class AgentHookContext:
    """Hook 上下文（借鉴 nanobot AgentHookContext）"""
    iteration: int = 0
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    tool_events: list[ToolEvent] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    error: str | None = None


class AgentHook(ABC):
    """
    Agent 钩子基类（借鉴 nanobot AgentHook）
    子类选择性覆写，不强制实现所有方法
    """

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        """工具执行前：参数校验 / 注入防护"""
        pass

    async def after_execute_tools(self, context: AgentHookContext) -> None:
        """工具执行后：结果脱敏 / 审计"""
        pass

    async def after_iteration(self, context: AgentHookContext) -> None:
        """每轮迭代后：usage 追踪 / 预算检查"""
        pass


# ═══════════════════════════════════════════════
#  审计 Hook：把工具调用写入 AuditLog
# ═══════════════════════════════════════════════

class AuditHook(AgentHook):
    """
    审计 Hook：工具调用写入 audit_log 表
    借鉴 nanobot 的审计写入 + LLD §3.2 的审计日志设计
    """

    def __init__(self, actor: str = "agent", agent_id: str = "", trace_id: str = ""):
        self.actor = actor
        self.agent_id = agent_id
        self.trace_id = trace_id

    async def after_execute_tools(self, context: AgentHookContext) -> None:
        """工具执行后写入审计日志"""
        # 延迟导入，避免循环依赖
        from backend.models.resource import AuditLog
        from backend.database import async_session
        import uuid

        try:
            async with async_session() as db:
                for evt in context.tool_events:
                    log = AuditLog(
                        id=uuid.uuid4().hex,
                        actor=self.actor,
                        action="tool_call",
                        target_type="tool",
                        target_id="",
                        target_name=evt.name,
                        detail=f"args={evt.arguments}, result_preview={evt.result[:200]}, error={evt.is_error}",
                        trace_id=self.trace_id,
                        decision="ALLOW" if not evt.is_error else "DENY",
                    )
                    db.add(log)
                await db.commit()
        except Exception as e:
            print(f"[AuditHook] 审计写入失败: {e}")


# ═══════════════════════════════════════════════
#  安全 Hook：参数注入防护 + 结果脱敏
# ═══════════════════════════════════════════════

# 敏感模式（借鉴 nanobot web.py 的 SSRF 校验 + LLD 的脱敏规则）
_SENSITIVE_PATTERNS = [
    "password", "secret", "token", "api_key", "apikey",
    "access_key", "private_key", "credential",
]
_REDACT_PLACEHOLDER = "[REDACTED]"


def _redact_sensitive(text: str, max_length: int = 8000) -> str:
    """
    结果脱敏（借鉴 nanobot 的结果截断 + LLD 的脱敏规则）
    1. 截断超长结果
    2. 替换敏感模式
    """
    if not text:
        return ""

    # 截断
    if len(text) > max_length:
        text = text[:max_length] + "\n...[truncated]"

    # 脱敏（简单字符串替换）
    lower = text.lower()
    for pattern in _SENSITIVE_PATTERNS:
        if pattern in lower:
            # 找到模式位置，替换后面的值
            idx = lower.find(pattern)
            # 简单替换：把 pattern 后面的 50 字符替换为 [REDACTED]
            start = idx + len(pattern)
            end = min(start + 50, len(text))
            text = text[:start] + _REDACT_PLACEHOLDER + text[end:]
            lower = text.lower()

    return text


def _check_injection(args: dict) -> str | None:
    """
    参数注入防护（借鉴 nanobot beforeTool 的参数校验）
    检查是否包含可疑注入模式
    """
    for key, value in args.items():
        if isinstance(value, str):
            # 检查 prompt injection 模式
            lower = value.lower()
            if "ignore previous" in lower or "system:" in lower:
                return f"参数 '{key}' 包含可疑注入模式"
            # 检查路径遍历
            if "../" in value or "..\\\\" in value:
                return f"参数 '{key}' 包含路径遍历模式"
    return None


class SecurityHook(AgentHook):
    """
    安全 Hook：参数注入防护 + 结果脱敏
    借鉴 nanobot beforeTool/afterTool + LLD PEP 设计
    """

    def __init__(self, read_only: bool = True):
        self.read_only = read_only
        self._blocked: list[str] = []

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        """工具执行前：参数注入防护"""
        for tc in context.tool_calls:
            injection = _check_injection(tc.arguments)
            if injection:
                self._blocked.append(f"{tc.name}: {injection}")
                print(f"[SecurityHook] 阻断: {injection}")
                # 标记为错误（runner 会跳过执行）
                tc.arguments = {"_blocked": True, "_reason": injection}

    async def after_execute_tools(self, context: AgentHookContext) -> None:
        """工具执行后：结果脱敏"""
        for evt in context.tool_events:
            if evt.result:
                evt.result = _redact_sensitive(evt.result)
