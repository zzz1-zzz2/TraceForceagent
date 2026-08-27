"""ToolRegistry：注册、查找、dispatch 所有 Tool。"""

from __future__ import annotations

from coding_agent.tools.base import Tool
from coding_agent.tools.filesystem import ListFilesTool, ReadFileTool
from coding_agent.tools.search import SearchCodeTool
from coding_agent.tools.patch import ApplyPatchTool
from coding_agent.tools.shell import RunCommandTool
from coding_agent.tools.git_ops import GitDiffTool
from coding_agent.tools.finish import FinishTool
from coding_agent.tools.plan import UpdatePlanTool


class ToolRegistry:
    """Tool 注册中心。"""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册一个 Tool。"""
        if tool.name in self._tools:
            raise ValueError(f"Tool {tool.name} already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """按名字查找 Tool。"""
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        """返回所有 Tool。"""
        return list(self._tools.values())

    def names(self) -> list[str]:
        """返回所有 Tool 名字。"""
        return list(self._tools.keys())

    def schemas(self) -> list[dict]:
        """返回 OpenAI function calling 格式的 schemas。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.schema,
                },
            }
            for tool in self._tools.values()
        ]


def default_registry() -> ToolRegistry:
    """构造默认 Registry（注册所有内置工具）。"""
    reg = ToolRegistry()
    reg.register(ListFilesTool())
    reg.register(ReadFileTool())
    reg.register(SearchCodeTool())
    reg.register(ApplyPatchTool())
    reg.register(RunCommandTool())
    reg.register(GitDiffTool())
    reg.register(UpdatePlanTool())
    reg.register(FinishTool())
    return reg