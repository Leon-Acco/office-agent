"""
MCP Client - 将 MCP Server 的远端工具接入 ToolRegistry

设计要点：
1. 官方 mcp 包（SSE transport，支持自定义 headers 鉴权）
2. Tool 表一行 = 一个 MCP Server；白名单含 server 的 name 即启用其全部远端工具
3. 连接失败静默降级：单 server 不可达只记日志跳过，不拖垮整场对话
4. 远端工具名加 mcp__<server>__ 前缀，防与内置工具冲突，且满足 OpenAI function name 规则
5. 生命周期核心约束：load_mcp_tools 内部绝不自建 async with——
   会话必须由调用方传入的 AsyncExitStack 持有，覆盖整个流式消费过程，
   否则 list_tools 完会话即关，后续 call_tool 时会话已死
"""
import asyncio
import json
import logging
import re
from contextlib import AsyncExitStack
from datetime import timedelta

from sqlalchemy import select

from backend.models.resource import Tool as ToolModel
from backend.runtime.tool_base import Tool, ToolResult

logger = logging.getLogger("mcp")

# OpenAI function name 规则：^[a-zA-Z0-9_-]{1,64}$
_FN_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]")


def _slug(text: str) -> str:
    """清洗为 function name 合法字符"""
    return _FN_NAME_RE.sub("_", text or "")[:40] or "server"


def _make_fn_name(server_key: str, remote_name: str) -> str:
    """生成带 server 前缀的工具名：mcp__<server>__<tool>，总长截断到 64"""
    return f"mcp__{_slug(server_key)}__{_slug(remote_name)}"[:64]


def _parse_config(config_str) -> dict:
    """容错解析 Tool.config JSON 文本，非法时返回 {}"""
    if not config_str:
        return {}
    if isinstance(config_str, dict):
        return config_str
    try:
        cfg = json.loads(config_str)
        return cfg if isinstance(cfg, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


class MCPTool(Tool):
    """单个远端 MCP 工具的本地代理（四要素契约）"""

    def __init__(self, session, server_key: str, remote_tool, timeout_ms: int):
        self._session = session                 # mcp ClientSession（生命周期由调用方的 AsyncExitStack 持有）
        self._remote_name = remote_tool.name    # 远端原始工具名
        self._fn_name = _make_fn_name(server_key, remote_tool.name)
        self._desc = remote_tool.description or f"MCP 工具 {remote_tool.name}"
        schema = remote_tool.inputSchema or {}
        # 兜底：必须是 object schema，否则 LLM API 会 400
        self._params = schema if schema.get("type") == "object" else {"type": "object", "properties": {}}
        self._timeout_ms = timeout_ms or 5000

    @property
    def name(self) -> str:
        return self._fn_name

    @property
    def description(self) -> str:
        return self._desc

    @property
    def parameters(self) -> dict:
        return self._params

    @property
    def read_only(self) -> bool:
        return False  # 远端工具语义未知，保守标记非只读

    async def execute(self, **kwargs) -> ToolResult:
        """调用远端工具，所有异常转为 ToolResult.error 不抛出"""
        try:
            result = await self._session.call_tool(
                self._remote_name, kwargs,
                read_timeout_seconds=timedelta(milliseconds=self._timeout_ms),
            )
        except Exception as e:
            return ToolResult.error(f"MCP 工具调用失败: {e}")
        # 拍平 content 数组：text 直取，其余类型 JSON 序列化
        parts = []
        for c in (result.content or []):
            if getattr(c, "type", None) == "text":
                parts.append(c.text)
            else:
                parts.append(json.dumps(c.model_dump(), ensure_ascii=False, default=str))
        text = "\n".join(parts) or "(无返回内容)"
        if getattr(result, "isError", False):
            return ToolResult.error(text)
        return ToolResult.ok(text)


async def _connect_one(stack: AsyncExitStack, endpoint: str, config: dict,
                       connect_timeout: float = 8.0):
    """
    建立单个 MCP Server 会话（SSE transport），会话注册在调用方的 stack 上
    返回初始化完成的 ClientSession；失败抛异常由调用方捕获降级
    """
    from mcp import ClientSession
    from mcp.client.sse import sse_client

    headers = config.get("headers") or {}
    read, write = await asyncio.wait_for(
        stack.enter_async_context(
            sse_client(endpoint, headers=headers, timeout=connect_timeout)
        ),
        timeout=connect_timeout + 2,
    )
    session = await stack.enter_async_context(ClientSession(read, write))
    await asyncio.wait_for(session.initialize(), timeout=connect_timeout)
    return session


async def load_mcp_tools(stack: AsyncExitStack, allowed_tools: list, db) -> list:
    """
    按白名单加载 MCP Server 工具，会话生命周期注册在调用方传入的 stack 上

    流程：查 Tool 表 type='mcp' AND state='APPROVED' AND name IN allowed_tools
          -> 逐 server 连接 + list_tools -> 包装为 MCPTool
    降级：单 server 连接失败只记日志跳过，不影响其他 server 与内置工具
    """
    if not allowed_tools:
        return []
    try:
        rows = (await db.execute(
            select(ToolModel).where(
                ToolModel.type == "mcp",
                ToolModel.state == "APPROVED",
                ToolModel.name.in_(allowed_tools),
            )
        )).scalars().all()
    except Exception as e:
        logger.warning(f"[mcp] 查询 Tool 表失败，跳过 MCP 加载: {e}")
        return []

    tools: list = []
    for row in rows:
        if not row.endpoint:
            continue
        config = _parse_config(row.config)
        server_key = row.tool_key or row.name
        try:
            session = await _connect_one(
                stack, row.endpoint, config,
                connect_timeout=max((row.timeout_ms or 5000) / 1000, 5),
            )
            listed = await asyncio.wait_for(session.list_tools(), timeout=10)
            remote_tools = listed.tools or []
            for rt in remote_tools:
                tools.append(MCPTool(session, server_key, rt, row.timeout_ms))
            logger.info(f"[mcp] {row.name}: 已接入 {len(remote_tools)} 个工具")
        except Exception as e:
            # 降级：单个 server 不可达不影响整场对话
            logger.warning(f"[mcp] {row.name} 连接失败，已跳过: {e}")
    return tools


async def test_mcp_connection(endpoint: str, config_str: str = "",
                              timeout_ms: int = 10000) -> dict:
    """
    测试连接（不落库）：连接 + initialize + list_tools，返回发现的工具清单
    供 admin 端点调用；自建短生命周期 stack，用完即关
    """
    config = _parse_config(config_str)
    async with AsyncExitStack() as stack:
        session = await _connect_one(stack, endpoint, config,
                                     connect_timeout=timeout_ms / 1000)
        listed = await asyncio.wait_for(session.list_tools(), timeout=15)
        return {
            "ok": True,
            "tools": [
                {
                    "name": t.name,
                    "description": (t.description or "")[:200],
                    # 透传参数 schema，供管理端展示参数表（无则 None）
                    "input_schema": getattr(t, "inputSchema", None),
                }
                for t in (listed.tools or [])
            ],
        }
