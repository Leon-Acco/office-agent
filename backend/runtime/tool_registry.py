"""
ToolRegistry - 借鉴 nanobot agent/tools/registry.py
适配 Office_Agent：从数据库 Tool 表 + 岗位包白名单加载

关键设计（借鉴 nanobot）：
1. 注册 + 校验 + 缓存工具定义
2. prepare_call 三步走：解析 -> 转换 -> 校验
3. 错误返回文本提示（含可用工具名），让模型自我纠错
4. 稳定排序（内建工具在前），利于 prompt 缓存命中
"""
from typing import Optional

from backend.runtime.tool_base import Tool, ToolResult


class ToolRegistry:
    """
    工具注册表（借鉴 nanobot ToolRegistry）
    绑定 Office_Agent：从岗位包白名单过滤可用工具
    """

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._cached_definitions: list[dict] | None = None

    def register(self, tool: Tool) -> None:
        """注册工具"""
        self._tools[tool.name] = tool
        self._cached_definitions = None  # 使缓存失效

    def unregister(self, name: str) -> None:
        """注销工具"""
        self._tools.pop(name, None)
        self._cached_definitions = None

    def get(self, name: str) -> Tool | None:
        """获取工具"""
        return self._tools.get(name)

    def get_definitions(self) -> list[dict]:
        """
        获取所有工具的 OpenAI function-calling 定义
        借鉴 nanobot：稳定排序 + 缓存
        """
        if self._cached_definitions is not None:
            return self._cached_definitions

        # 按 name 排序，保证稳定顺序（利于 prompt 缓存）
        sorted_tools = sorted(self._tools.values(), key=lambda t: t.name)
        self._cached_definitions = [t.to_schema() for t in sorted_tools]
        return self._cached_definitions

    def get_available_names(self) -> list[str]:
        """获取所有已注册工具名（给模型的错误提示用）"""
        return sorted(self._tools.keys())

    def prepare_call(self, name: str, params: dict) -> tuple[Tool | None, dict, str | None]:
        """
        准备工具调用：解析 -> 转换 -> 校验
        借鉴 nanobot prepare_call：错误返回文本提示而非抛异常

        Returns:
            (tool, params, error_message)
            - 成功：(tool, cast_params, None)
            - 失败：(None or tool, params, error_message)
        """
        tool = self._tools.get(name)
        if not tool:
            available = self.get_available_names()
            return None, params, f"工具 '{name}' 不存在。可用工具: {available}"

        # 简单类型转换（借鉴 nanobot cast_params）
        cast_params = self._cast_params(tool, params)

        # 校验必填参数（借鉴 nanobot validate_params）
        errors = self._validate_params(tool, cast_params)
        if errors:
            return tool, cast_params, f"参数校验失败: {'; '.join(errors)}"

        return tool, cast_params, None

    def _cast_params(self, tool: Tool, params: dict) -> dict:
        """简单类型转换（借鉴 nanobot _cast_value）"""
        schema = tool.parameters
        properties = schema.get("properties", {})
        cast = {}
        for key, value in params.items():
            prop = properties.get(key, {})
            prop_type = prop.get("type", "string")
            if prop_type == "boolean" and isinstance(value, str):
                cast[key] = value.lower() in ("true", "1", "yes")
            elif prop_type == "integer" and isinstance(value, str):
                try:
                    cast[key] = int(value)
                except ValueError:
                    cast[key] = value
            elif prop_type == "number" and isinstance(value, str):
                try:
                    cast[key] = float(value)
                except ValueError:
                    cast[key] = value
            else:
                cast[key] = value
        return cast

    def _validate_params(self, tool: Tool, params: dict) -> list[str]:
        """校验必填参数（借鉴 nanobot validate_params）"""
        schema = tool.parameters
        required = schema.get("required", [])
        errors = []
        for req in required:
            if req not in params or params[req] is None or params[req] == "":
                errors.append(f"缺少必填参数: {req}")
        return errors

    async def execute(self, name: str, params: dict) -> ToolResult:
        """
        执行工具（完整流程：prepare_call -> execute）
        借鉴 nanobot：错误返回 ToolResult.error 而非抛异常
        """
        tool, cast_params, error = self.prepare_call(name, params)
        if error:
            return ToolResult.error(error)
        try:
            return await tool.execute(**cast_params)
        except Exception as e:
            return ToolResult.error(f"工具执行异常: {e}")
