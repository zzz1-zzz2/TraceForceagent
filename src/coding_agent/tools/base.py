"""Tool 抽象基类。

所有 Tool 必须实现：
- name: 唯一名称
- description: 模型看的描述
- schema: JSON Schema（OpenAI function calling 格式）
- execute(args, runtime) -> ToolResult

子类可重写：
- validate_args(args): 返回错误信息列表（空列表表示合法）
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # TYPE_CHECKING 块只在静态分析时执行，避免 tools ↔ model 包循环导入。
    # 运行时通过函数内 lazy import 使用 ToolResult。
    from coding_agent.model.types import ToolResult


class Tool(ABC):
    """Tool 抽象基类。"""

    name: str = ""
    description: str = ""
    schema: dict = {}

    @abstractmethod
    def execute(self, args: dict, runtime) -> "ToolResult":
        """执行工具，返回结果。"""
        raise NotImplementedError

    def validate_args(self, args: dict) -> list[str]:
        """校验参数，返回错误信息列表。

        V1 简化：不依赖 jsonschema 库，基础类型检查。
        """
        errors: list[str] = []

        # Tool.schema 是 JSON Schema 的 parameters 部分（即包含 type/properties/required）
        required = self.schema.get("required", [])
        properties = self.schema.get("properties", {})

        for key in required:
            if key not in args:
                errors.append(f"missing required parameter '{key}'")

        for key, value in args.items():
            if key not in properties:
                # 不报错（额外字段可能无害），但记录
                continue
            expected_type = properties[key].get("type")
            if not expected_type:
                continue

            if not self._check_type(value, expected_type):
                errors.append(
                    f"parameter '{key}' expects {expected_type}, "
                    f"got {type(value).__name__}: {value}"
                )

        return errors

    def _check_type(self, value: Any, expected: str) -> bool:
        """基础类型检查。"""
        if expected == "string":
            return isinstance(value, str)
        if expected == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if expected == "boolean":
            return isinstance(value, bool)
        if expected == "array":
            return isinstance(value, list)
        if expected == "object":
            return isinstance(value, dict)
        return True  # unknown type: pass

    def unknown_tool_observation(self, tool_name: str) -> "ToolResult":
        """默认的 unknown tool Observation（子类一般不用改）。"""
        from coding_agent.model.types import ToolResult
        return ToolResult.fail(f"Unknown tool: {tool_name}")

    def exception_observation(self, e: Exception) -> "ToolResult":
        """异常时返回 Observation（子类可定制更友好的错误信息）。"""
        from coding_agent.model.types import ToolResult
        return ToolResult.fail(
            f"Tool {self.name} raised exception: {type(e).__name__}: {e}",
            is_runtime_error=True,
        )
