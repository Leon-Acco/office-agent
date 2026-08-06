"""
Tool 基类 - 借鉴 nanobot agent/tools/base.py
适配 Office_Agent：绑定数据库 Tool 表 + 治理域策略

关键设计（借鉴 nanobot）：
1. 四要素契约：name / description / parameters(JSON Schema) / execute
2. read_only 标记：只读工具可并发
3. concurrency_safe：read_only && !exclusive
4. ToolResult：继承 str，带 is_error 状态
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


class ToolResult(str):
    """
    工具执行结果（借鉴 nanobot ToolResult）
    继承 str 兼容"直接喂回模型"，同时携带 is_error 语义
    """
    def __new__(cls, value: str, is_error: bool = False):
        instance = super().__new__(cls, value)
        instance.is_error = is_error
        return instance

    @classmethod
    def error(cls, message: str) -> "ToolResult":
        return cls(message, is_error=True)

    @classmethod
    def ok(cls, content: str) -> "ToolResult":
        return cls(content, is_error=False)


class Tool(ABC):
    """
    工具抽象基类（借鉴 nanobot Tool ABC）
    四要素：name / description / parameters / execute
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """工具唯一标识"""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述（给 LLM 看的）"""
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict:
        """JSON Schema 参数定义"""
        ...

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """执行工具"""
        ...

    @property
    def read_only(self) -> bool:
        """是否只读（无副作用）-> 可并发"""
        return True

    @property
    def exclusive(self) -> bool:
        """是否排他（不可与其他工具同时执行）"""
        return False

    @property
    def concurrency_safe(self) -> bool:
        """是否并发安全（借鉴 nanobot：read_only && !exclusive）"""
        return self.read_only and not self.exclusive

    def to_schema(self) -> dict:
        """
        转为 OpenAI function-calling 格式
        借鉴 nanobot to_schema()：直接产出给模型的接口文档
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
