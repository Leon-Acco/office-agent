"""
LLM Provider - 借鉴 nanobot providers/base.py
适配 Office_Agent：封装智谱 BigModel Anthropic 兼容端点（GLM-5.2，原生 1M 上下文）

关键设计（借鉴 nanobot）：
1. 统一抽象：chat() + chat_stream() 两种调用方式
2. 重试与容错内建在基类（瞬时错误识别 + 退避）
3. 畸形 tool_call 清洗（在写入历史前丢弃）
4. 异常转错误响应（不击穿整个回合）

协议说明：
- 内部历史保持 OpenAI 格式（runner/历史存储不变），仅在发送时翻译为 Anthropic Messages 格式
- system 消息抽取为顶层 system 字段；assistant.tool_calls -> tool_use 内容块；
  role=tool -> user 消息内的 tool_result 块（连续的合并为一条 user 消息）
- 工具定义由 OpenAI function 格式转为 {name, description, input_schema}
"""
import json
import asyncio
from dataclasses import dataclass, field
from typing import AsyncIterator

import httpx

from backend.config import (
    LLM_BASE_URL,
    LLM_API_KEY,
    LLM_MODEL,
    LLM_MAX_TOKENS,
    LLM_TEMPERATURE,
    LLM_TIMEOUT,
    LLM_CONCURRENCY,
)


# ═══════════════════════════════════════════════
#  数据类（借鉴 nanobot LLMResponse / ToolCallRequest）
# ═══════════════════════════════════════════════

@dataclass
class ToolCallRequest:
    """LLM 发出的工具调用请求"""
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    """统一响应（借鉴 nanobot LLMResponse）"""
    content: str = ""
    finish_reason: str = "stop"  # stop / tool_calls / length / error
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    usage: dict = field(default_factory=dict)

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0

    @property
    def is_final(self) -> bool:
        """是否为终答（无工具调用）"""
        return not self.has_tool_calls and self.finish_reason != "error"


# ═══════════════════════════════════════════════
#  OpenAI 内部格式 -> Anthropic wire 格式 翻译层
# ═══════════════════════════════════════════════

# Anthropic stop_reason -> 内部 finish_reason 映射
_STOP_REASON_MAP = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "tool_use": "tool_calls",
    "max_tokens": "length",
}


def _parse_arguments(args) -> dict:
    """工具参数容错解析（字符串 JSON / dict / 畸形 -> dict）"""
    if isinstance(args, dict):
        return args
    try:
        parsed = json.loads(args) if isinstance(args, str) else {}
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def to_anthropic_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    """
    将 OpenAI 风格的内部消息历史翻译为 Anthropic Messages 格式

    返回 (system_text, anthropic_messages)：
    1. 所有 system 消息内容拼接为顶层 system 字符串
    2. assistant.tool_calls 转为 tool_use 内容块
    3. role=tool 转为 user 消息内的 tool_result 块，连续的 tool 结果合并进同一条 user
    4. 相邻同角色消息合并（Anthropic 要求 user/assistant 严格交替）
    """
    system_parts: list[str] = []
    converted: list[dict] = []

    for m in messages:
        role = m.get("role")
        if role == "system":
            if m.get("content"):
                system_parts.append(str(m["content"]))
            continue

        if role == "assistant":
            blocks = []
            text = m.get("content") or ""
            if text:
                blocks.append({"type": "text", "text": str(text)})
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function", {})
                blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": fn.get("name", ""),
                    "input": _parse_arguments(fn.get("arguments", "{}")),
                })
            if not blocks:
                # Anthropic 不接受空内容消息，占位防空
                blocks = [{"type": "text", "text": " "}]
            converted.append({"role": "assistant", "content": blocks})
            continue

        if role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": m.get("tool_call_id", ""),
                "content": str(m.get("content", "")) or "(无输出)",
            }
            # 连续的 tool 结果合并进上一条 tool_result user 消息
            if (converted and converted[-1]["role"] == "user"
                    and isinstance(converted[-1]["content"], list)
                    and converted[-1]["content"]
                    and converted[-1]["content"][0].get("type") == "tool_result"):
                converted[-1]["content"].append(block)
            else:
                converted.append({"role": "user", "content": [block]})
            continue

        # 普通 user 消息
        converted.append({"role": "user", "content": str(m.get("content", "")) or " "})

    # 相邻同角色合并（历史里可能出现连续 user/assistant）
    merged: list[dict] = []
    for msg in converted:
        if merged and merged[-1]["role"] == msg["role"]:
            prev, cur = merged[-1]["content"], msg["content"]
            prev_list = prev if isinstance(prev, list) else [{"type": "text", "text": prev}]
            cur_list = cur if isinstance(cur, list) else [{"type": "text", "text": cur}]
            merged[-1]["content"] = prev_list + cur_list
        else:
            merged.append(msg)

    return "\n\n".join(system_parts), merged


def to_anthropic_tools(tools: list[dict] | None) -> list[dict]:
    """OpenAI function 定义 -> Anthropic tools 格式（input_schema）"""
    out = []
    for t in tools or []:
        fn = t.get("function", {})
        out.append({
            "name": fn.get("name", ""),
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
        })
    return out


# ═══════════════════════════════════════════════
#  Provider 实现
# ═══════════════════════════════════════════════

# 瞬时错误标记（借鉴 nanobot _TRANSIENT_ERROR_MARKERS）
_TRANSIENT_MARKERS = ("429", "rate limit", "500", "502", "503", "504",
                       "overloaded", "timeout", "connection", "server error")
# 退避序列（秒）：协作会议室多人并发场景给足恢复窗口
_RETRY_DELAYS = (1, 2, 4, 8)


def _is_transient_error(error: Exception) -> bool:
    """
    判断是否为可重试的瞬时错误
    注意:httpx 的 ReadTimeout/ConnectError 等 str(e) 为空串,
    仅靠消息匹配会把超时误判为不可重试 → 必须按异常类型判断
    (协作会议室 [LLM 调用失败: ] 空消息的根因)
    """
    # 超时/连接层错误一律视为瞬时(排队重试而非立即失败)
    if isinstance(error, (httpx.TimeoutException, httpx.TransportError)):
        return True
    # HTTP 状态错误:429 与 5xx 可重试
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        return status == 429 or status >= 500
    msg = str(error).lower()
    return any(m in msg for m in _TRANSIENT_MARKERS)


def _err_text(error: Exception) -> str:
    """异常描述:str(e) 为空时补上类名,保证错误信息不为空"""
    text = str(error).strip()
    return text if text else type(error).__name__


# 全局并发闸:chat / chat_stream / services.llm.chat_completion 共用,
# 把会议室多子任务并发 + 前台聊天叠加产生的请求压在智谱配额内(排队而非 429)
_LLM_SEMAPHORE = asyncio.Semaphore(LLM_CONCURRENCY)

# 模块级共享 AsyncClient(连接池复用,避免每次调用新建 TCP/TLS 握手)
_shared_client: httpx.AsyncClient | None = None


def _get_shared_client() -> httpx.AsyncClient:
    """获取共享 AsyncClient(uvicorn 单事件循环生命周期内复用,无需关闭)"""
    global _shared_client
    if _shared_client is None:
        _shared_client = httpx.AsyncClient(timeout=LLM_TIMEOUT)
    return _shared_client


def _drop_malformed_tool_calls(tool_calls: list) -> list[ToolCallRequest]:
    """
    畸形 tool_call 清洗（借鉴 nanobot _drop_malformed_tool_calls）
    在写入历史前丢弃 name 缺失/非字符串的 tool_call，避免坏消息卡死会话
    （流式累积仍用 OpenAI 形状的 dict 作中间结构，复用本清洗逻辑）
    """
    clean = []
    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        name = tc.get("function", {}).get("name", "")
        if not name or not isinstance(name, str):
            continue
        clean.append(ToolCallRequest(
            id=tc.get("id", ""),
            name=name,
            arguments=_parse_arguments(tc.get("function", {}).get("arguments", "{}")),
        ))
    return clean


class LLMProvider:
    """
    LLM 后端 Provider（借鉴 nanobot LLMProvider）
    封装智谱 Anthropic 兼容端点 GLM-5.2，支持 function calling + 流式输出
    """

    def __init__(
        self,
        base_url: str = LLM_BASE_URL,
        api_key: str = LLM_API_KEY,
        model: str = LLM_MODEL,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def _build_headers(self) -> dict:
        # x-api-key 与 Bearer 双发，兼容智谱网关两种鉴权习惯
        return {
            "x-api-key": self.api_key,
            "Authorization": f"Bearer {self.api_key}",
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    def _build_payload(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tool_choice: str | None = None,
    ) -> dict:
        """构建 Anthropic Messages 请求体（内部 OpenAI 历史在此翻译）"""
        system, converted = to_anthropic_messages(messages)
        payload = {
            "model": self.model,
            "messages": converted,
            "temperature": temperature if temperature is not None else LLM_TEMPERATURE,
            "max_tokens": max_tokens or LLM_MAX_TOKENS,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = to_anthropic_tools(tools)
            if tool_choice:
                # OpenAI 风格 tool_choice -> Anthropic 风格
                payload["tool_choice"] = {
                    "auto": {"type": "auto"},
                    "none": {"type": "none"},
                    "required": {"type": "any"},
                }.get(tool_choice, {"type": "auto"})
        return payload

    @staticmethod
    def _parse_message(data: dict) -> LLMResponse:
        """解析 Anthropic 非流式响应：text 块拼接 + tool_use 块提取"""
        texts = []
        tool_calls = []
        for block in data.get("content", []):
            btype = block.get("type")
            if btype == "text":
                texts.append(block.get("text", ""))
            elif btype == "tool_use":
                name = block.get("name", "")
                if name:  # 畸形清洗：无名 tool_use 直接丢弃
                    tool_calls.append(ToolCallRequest(
                        id=block.get("id", ""),
                        name=name,
                        arguments=_parse_arguments(block.get("input") or {}),
                    ))
        finish_reason = _STOP_REASON_MAP.get(data.get("stop_reason") or "end_turn", "stop")
        if tool_calls:
            finish_reason = "tool_calls"
        return LLMResponse(
            content="".join(texts),
            finish_reason=finish_reason,
            tool_calls=tool_calls,
            usage=data.get("usage", {}),
        )

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """
        同步调用（阻塞直到完整返回）
        借鉴 nanobot chat_with_retry：瞬时错误自动重试
        """
        payload = self._build_payload(messages, tools, temperature, max_tokens)

        # 整个调用(含重试)占一个并发名额,排队等待而非触发 429
        async with _LLM_SEMAPHORE:
            client = _get_shared_client()
            for attempt, delay in enumerate(_RETRY_DELAYS + (None,)):
                try:
                    resp = await client.post(
                        f"{self.base_url}/v1/messages",
                        headers=self._build_headers(),
                        json=payload,
                    )
                    resp.raise_for_status()
                    return self._parse_message(resp.json())

                except Exception as e:
                    if delay is None or not _is_transient_error(e):
                        # 不可重试的错误，转为错误响应（借鉴 nanobot _safe_chat）
                        return LLMResponse(
                            content=f"[LLM 调用失败: {_err_text(e)}]",
                            finish_reason="error",
                        )
                    await asyncio.sleep(delay)

        return LLMResponse(content="[LLM 重试耗尽]", finish_reason="error")

    async def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[tuple[str, LLMResponse | None]]:
        """
        流式调用包装(带容错,签名与返回不变)

        容错策略(可慢不能断):
        - 首个 chunk 产出前(连接建立/首包阶段)的瞬时错误:整次安全重试,退避 _RETRY_DELAYS
        - 已产出内容后中断:不重试(避免重复下发),异常上抛由 runner 发 error 事件,
          前端保留已渲染的部分内容
        - 每次尝试占一个并发名额(_LLM_SEMAPHORE),与 chat() 共用限流
        """
        for attempt, delay in enumerate(_RETRY_DELAYS + (None,)):
            produced = False  # 本次尝试是否已向下游产出过内容
            try:
                async with _LLM_SEMAPHORE:
                    async for item in self._chat_stream_once(
                        messages, tools, temperature, max_tokens
                    ):
                        produced = True
                        yield item
                return
            except Exception as e:
                if produced or delay is None or not _is_transient_error(e):
                    raise
                # 未产出任何内容,整次重试不会重复下发,安全
                await asyncio.sleep(delay)

    async def _chat_stream_once(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[tuple[str, LLMResponse | None]]:
        """
        流式调用单次尝试(逐 token yield)
        返回 (chunk_text, None) 表示文本块
        返回 ("", LLMResponse) 表示完成（含 tool_calls）

        借鉴 nanobot chat_stream：流式增量 + 完成时解析 tool_calls
        """
        payload = self._build_payload(messages, tools, temperature, max_tokens)
        payload["stream"] = True

        accumulated_content = ""
        accumulated_tool_calls = []  # OpenAI 形状中间结构，复用畸形清洗
        finish_reason = "stop"
        usage = {}

        client = _get_shared_client()
        async with client.stream(
            "POST",
            f"{self.base_url}/v1/messages",
            headers=self._build_headers(),
            json=payload,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue

                evt = json.loads(line[6:])
                evt_type = evt.get("type")

                # 内容块开始：tool_use 块在此携带 id/name
                if evt_type == "content_block_start":
                    block = evt.get("content_block", {})
                    if block.get("type") == "tool_use":
                        idx = evt.get("index", 0)
                        while len(accumulated_tool_calls) <= idx:
                            accumulated_tool_calls.append(
                                {"id": "", "function": {"name": "", "arguments": ""}})
                        slot = accumulated_tool_calls[idx]
                        slot["id"] = block.get("id", "")
                        slot["function"]["name"] = block.get("name", "")
                    continue

                if evt_type == "content_block_delta":
                    delta = evt.get("delta", {})
                    # 文本增量
                    if delta.get("type") == "text_delta":
                        text = delta.get("text", "")
                        if text:
                            accumulated_content += text
                            yield (text, None)
                    # 工具参数增量（input_json_delta 按 index 拼接 partial_json，
                    # 与 OpenAI 流式同构：逐片 append 才能拼出完整 JSON）
                    elif delta.get("type") == "input_json_delta":
                        idx = evt.get("index", 0)
                        while len(accumulated_tool_calls) <= idx:
                            accumulated_tool_calls.append(
                                {"id": "", "function": {"name": "", "arguments": ""}})
                        accumulated_tool_calls[idx]["function"]["arguments"] += \
                            delta.get("partial_json", "")
                    continue

                # 结束原因 + usage
                if evt_type == "message_delta":
                    stop = (evt.get("delta") or {}).get("stop_reason")
                    if stop:
                        finish_reason = _STOP_REASON_MAP.get(stop, "stop")
                    if evt.get("usage"):
                        usage = evt["usage"]
                    continue

                # 流内错误事件（如 overloaded 中途失败）
                if evt_type == "error":
                    err = evt.get("error", {})
                    raise RuntimeError(f"流式调用中途失败: {err.get('type')} {err.get('message')}")

        # 流结束后，如果有 tool_calls，解析并返回完整响应
        clean_calls = _drop_malformed_tool_calls(accumulated_tool_calls)
        if clean_calls:
            final_response = LLMResponse(
                content=accumulated_content,
                finish_reason="tool_calls",
                tool_calls=clean_calls,
                usage=usage,
            )
            yield ("", final_response)
        else:
            final_response = LLMResponse(
                content=accumulated_content,
                finish_reason=finish_reason,
                usage=usage,
            )
            yield ("", final_response)
