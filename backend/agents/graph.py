"""
LangGraph Agent 图 - 用 create_react_agent 替代手动 StateGraph
create_react_agent 是 LangGraph 预置的 ReAct Agent，内置了消息格式兼容处理
"""
from typing import TypedDict
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.prebuilt import create_react_agent

from backend.agents.llm import get_llm
from backend.agents.tools import get_all_tools


def build_agent(
    system_prompt: str,
    tools: list[BaseTool] | None = None,
):
    """
    用 create_react_agent 构建 Agent
    自动处理消息格式兼容性
    """
    if tools is None:
        tools = get_all_tools()

    llm = get_llm()
    agent = create_react_agent(llm, tools)
    return agent


async def run_agent(
    question: str,
    system_prompt: str,
    history: list[dict] | None = None,
    tools: list[BaseTool] | None = None,
) -> dict:
    """执行 Agent（非流式）"""
    agent = build_agent(system_prompt, tools)

    messages = [SystemMessage(content=system_prompt)]
    if history:
        for h in history:
            if h["role"] == "user":
                messages.append(HumanMessage(content=h["content"]))
    messages.append(HumanMessage(content=question))

    result = await agent.ainvoke({"messages": messages})

    last_msg = result["messages"][-1]
    answer = last_msg.content if hasattr(last_msg, "content") else str(last_msg)

    tools_used = []
    for msg in result["messages"]:
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                tools_used.append(tc.get("name", "unknown"))

    return {
        "answer": answer,
        "tools_used": tools_used,
        "iterations": 0,
    }


async def stream_agent(
    question: str,
    system_prompt: str,
    history: list[dict] | None = None,
    tools: list[BaseTool] | None = None,
    max_iterations: int = 8,
):
    """执行 Agent（流式）"""
    try:
        agent = build_agent(system_prompt, tools)

        messages = [SystemMessage(content=system_prompt)]
        if history:
            for h in history:
                if h["role"] == "user":
                    messages.append(HumanMessage(content=h["content"]))
        messages.append(HumanMessage(content=question))

        tools_used = []

        async for event in agent.astream(
            {"messages": messages},
            stream_mode="values",
        ):
            last_msg = event["messages"][-1] if event.get("messages") else None
            if last_msg is None:
                continue

            # 工具调用
            if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                for tc in last_msg.tool_calls:
                    tools_used.append(tc.get("name", "unknown"))
                    yield {
                        "type": "tool.start",
                        "name": tc.get("name", "unknown"),
                        "arguments": tc.get("args", {}),
                    }

            # 工具结果（ToolMessage）
            from langchain_core.messages import ToolMessage
            if isinstance(last_msg, ToolMessage):
                yield {
                    "type": "tool.result",
                    "name": getattr(last_msg, "name", "unknown"),
                    "result": str(last_msg.content)[:500],
                    "is_error": False,
                }

            # LLM 文本输出
            if not isinstance(last_msg, ToolMessage) and hasattr(last_msg, "content") and last_msg.content:
                if not hasattr(last_msg, "tool_calls") or not last_msg.tool_calls:
                    yield {
                        "type": "answer.chunk",
                        "content": last_msg.content,
                    }

        yield {
            "type": "answer.completed",
            "tools_used": tools_used,
            "iterations": 0,
        }

    except Exception as e:
        yield {"type": "error", "message": str(e)}
