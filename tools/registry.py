"""Tool 注册和发现机制。"""

from typing import Any

from pydantic import BaseModel

from tools.base import BaseTool


class ToolAlreadyRegisteredError(ValueError):
    """Tool name 已经存在。"""


class ToolNotFoundError(LookupError):
    """Registry 中不存在指定 Tool。"""


class ToolRegistry:
    """保存唯一 Tool name 与实例的映射。"""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """注册 Tool，并拒绝同名覆盖。"""

        if not isinstance(tool, BaseTool):
            raise TypeError("只能注册 BaseTool 实例。")
        if not tool.name or not tool.description:
            raise ValueError("Tool 必须提供 name 和 description。")
        if not isinstance(tool.args_schema, type) or not issubclass(
            tool.args_schema, BaseModel
        ):
            raise TypeError("Tool args_schema 必须是 Pydantic BaseModel。")
        if tool.name in self._tools:
            raise ToolAlreadyRegisteredError(f"Tool name 已注册：{tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        """返回指定 Tool；未知 name 产生明确异常。"""

        try:
            return self._tools[name]
        except KeyError as error:
            raise ToolNotFoundError(f"未找到 Tool：{name}") from error

    def list_tools(self) -> list[dict[str, Any]]:
        """返回按 name 排序且包含 JSON Schema 的 metadata。"""

        return [
            {
                "name": tool.name,
                "description": tool.description,
                "args_schema": tool.args_schema.model_json_schema(),
            }
            for tool in sorted(self._tools.values(), key=lambda item: item.name)
        ]
