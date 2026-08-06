"""
智谱 BigModel LLM 服务（GLM-5.2，原生 1M 上下文）
通过 Anthropic 兼容接口调用（/api/anthropic/v1/messages）
"""
import json
import asyncio
import httpx
from typing import AsyncIterator

from backend.config import (
    LLM_BASE_URL,
    LLM_API_KEY,
    LLM_MODEL,
    LLM_MAX_TOKENS,
    LLM_TEMPERATURE,
    LLM_TIMEOUT,
)
# 复用 provider 的瞬时错误识别/退避序列/全局并发闸(单点约束所有 LLM 调用来源)
from backend.runtime.provider import _is_transient_error, _RETRY_DELAYS, _LLM_SEMAPHORE


def _build_headers() -> dict:
    """Anthropic 兼容端点请求头（x-api-key 与 Bearer 双发兼容网关）"""
    return {
        "x-api-key": LLM_API_KEY,
        "Authorization": f"Bearer {LLM_API_KEY}",
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }


def _split_system(messages: list[dict]) -> tuple[str, list[dict]]:
    """抽取 system 消息为顶层字段（Anthropic 协议要求），其余原样保留"""
    system_parts = [str(m["content"]) for m in messages if m.get("role") == "system" and m.get("content")]
    rest = [{"role": m["role"], "content": m.get("content", "")}
            for m in messages if m.get("role") in ("user", "assistant")]
    return "\n\n".join(system_parts), rest


def _extract_text(data: dict) -> str:
    """从 Anthropic 响应的内容块数组中拼接文本"""
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


async def chat_completion(
    messages: list[dict],
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """
    同步获取 LLM 回复（阻塞直到完整返回）

    Args:
        messages: OpenAI 格式消息列表 [{"role": "system/user/assistant", "content": "..."}]
        temperature: 采样温度，默认 0.7
        max_tokens: 最大生成 token 数

    Returns:
        LLM 回复文本
    """
    system, rest = _split_system(messages)
    payload = {
        "model": LLM_MODEL,
        "messages": rest,
        "temperature": temperature if temperature is not None else LLM_TEMPERATURE,
        "max_tokens": max_tokens or LLM_MAX_TOKENS,
    }
    if system:
        payload["system"] = system

    # 瞬时错误(429/5xx/超时等)退避重试 + 全局并发闸限流:
    # 会议室多子任务并发场景下排队等待而非直接 429 失败(可慢不能断);
    # 重试耗尽仍上抛,保持调用方(_decompose_task/分诊/AI 生成)原有异常契约
    for attempt, delay in enumerate(_RETRY_DELAYS + (None,)):
        try:
            async with _LLM_SEMAPHORE:
                async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
                    resp = await client.post(
                        f"{LLM_BASE_URL}/v1/messages",
                        headers=_build_headers(),
                        json=payload,
                    )
                    resp.raise_for_status()
                    return _extract_text(resp.json())
        except Exception as e:
            if delay is None or not _is_transient_error(e):
                raise
            await asyncio.sleep(delay)


async def chat_completion_stream(
    messages: list[dict],
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> AsyncIterator[str]:
    """
    流式获取 LLM 回复（逐 token yield）

    Args:
        messages: OpenAI 格式消息列表

    Yields:
        每个 token 块的文本内容
    """
    system, rest = _split_system(messages)
    payload = {
        "model": LLM_MODEL,
        "messages": rest,
        "temperature": temperature if temperature is not None else LLM_TEMPERATURE,
        "max_tokens": max_tokens or LLM_MAX_TOKENS,
        "stream": True,
    }
    if system:
        payload["system"] = system

    async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
        async with client.stream(
            "POST",
            f"{LLM_BASE_URL}/v1/messages",
            headers=_build_headers(),
            json=payload,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                evt = json.loads(line[6:])
                # 只透传文本增量，ping/工具块/结束事件忽略
                if evt.get("type") == "content_block_delta":
                    delta = evt.get("delta", {})
                    if delta.get("type") == "text_delta" and delta.get("text"):
                        yield delta["text"]


async def test_connection() -> dict:
    """测试 LLM 连接是否正常（Anthropic 兼容端点）"""
    url = f"{LLM_BASE_URL.rstrip('/')}/v1/messages"
    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": "你好，请回复OK确认连接正常"}],
        "max_tokens": 64,
    }

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.post(url, headers=_build_headers(), json=payload)
            if resp.status_code == 200:
                reply = _extract_text(resp.json())
                return {"status": "ok", "model": LLM_MODEL, "endpoint": url, "reply": reply.strip()}
            if resp.status_code in (401, 403):
                return {"status": "error", "model": LLM_MODEL, "endpoint": url,
                        "error": f"认证失败({resp.status_code})，请检查 API Key"}
            return {"status": "error", "model": LLM_MODEL, "endpoint": url,
                    "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            return {"status": "error", "model": LLM_MODEL, "endpoint": url, "error": str(e)}
