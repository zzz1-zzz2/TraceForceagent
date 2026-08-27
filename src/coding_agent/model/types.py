"""Model 通信的数据类型。

设计原则：
- 把 SDK 的原始响应归一为内部类型，便于跨 provider 切换
- 所有类型都用 dataclass / pydantic，便于序列化到 trajectory
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


# ============================================================
# LLM 响应
# ============================================================


@dataclass
class TokenUsage:
    """Token 使用统计。"""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class ToolCall:
    """单个 tool call（已归一化）。"""

    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str = ""  # 原始 JSON 字符串（debug 用）


@dataclass
class ModelResponse:
    """LLM 的归一化响应。"""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = ""  # stop / tool_calls / length / content_filter
    usage: TokenUsage = field(default_factory=TokenUsage)
    raw: Any = None  # 原始 Provider 响应（debug 用）


# ============================================================
# Agent Action
# ============================================================


@dataclass
class AgentAction:
    """解析后的内部 Agent Action。"""

    is_finish: bool = False
    is_invalid: bool = False

    # ToolAction 字段
    tool_name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    raw_response: Any = None
    action_id: str = ""

    # FinishAction 字段
    summary: str = ""
    validation: str = ""
    notes: str = ""

    # InvalidAction 字段
    error_msg: str = ""

    @property
    def args_hash(self) -> str:
        """参数归一化 hash，用于重复动作检测。"""
        canonical = json.dumps(self.arguments, ensure_ascii=False, sort_keys=True)
        return hashlib.md5(canonical.encode()).hexdigest()[:12]


@dataclass
class FinishAction(AgentAction):
    """显式 Finish Action。"""

    def __init__(self, summary: str, validation: str = "", notes: str = ""):
        super().__init__(is_finish=True)
        self.summary = summary
        self.validation = validation
        self.notes = notes


@dataclass
class ToolAction(AgentAction):
    """合法 Tool Action。"""

    def __init__(
        self,
        tool_name: str,
        arguments: dict,
        action_id: str = "",
        raw_response: Any = None,
    ):
        super().__init__(is_finish=False)
        self.tool_name = tool_name
        self.arguments = arguments
        self.action_id = action_id
        self.raw_response = raw_response


@dataclass
class InvalidAction(AgentAction):
    """非法 Action（如模型输出空、未知 tool、参数错误）。"""

    def __init__(self, error_msg: str):
        super().__init__(is_invalid=True, error_msg=error_msg)


# ============================================================
# Tool 执行结果
# ============================================================


@dataclass
class ToolResult:
    """工具执行结果。"""

    success: bool
    content: str  # 给模型看的文本
    error: str = ""
    truncated: bool = False
    is_validation_failure: bool = False  # pytest exit 1 标记
    is_runtime_error: bool = False  # timeout / executable not found
    is_timeout: bool = False  # 命令 timeout（细分自 is_runtime_error）
    summary: str = ""  # 简短摘要（用于 Working State）

    @classmethod
    def ok(cls, content: str, **kwargs) -> "ToolResult":
        return cls(success=True, content=content, **kwargs)

    @classmethod
    def fail(cls, error: str, **kwargs) -> "ToolResult":
        return cls(success=False, content=error, error=error, **kwargs)


# 别名（语义化）
Observation = ToolResult