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
    # P2-1E.1: 如果 SDK 给出的 arguments JSON 解析失败，保留错误诊断。
    # 解析器可以根据此字段构造明确的协议失败，避免静默退化为 {}。
    arguments_parse_error: str | None = None


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
    # P2-1E.1: 协议级失败（截断 / 非法 JSON / 多调用 / finish_reason 拒绝），
    # 与"未知 tool / 参数错误"等语义失败区分；trajectory 和 feedback 会
    # 用不同 kind 记录，但 loop 仍走同一 [InvalidAction] 反馈路径。
    is_protocol_failure: bool = False

    # ToolAction 字段
    tool_name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    raw_response: Any = None
    action_id: str = ""
    # P2-1E.1: 当模型在 ToolCall 之外还输出了文本（preamble），原文保留在此。
    # 当前不影响 loop 行为，仅供 trajectory / 未来 AssistantReply 反馈使用。
    preamble: str = ""

    # FinishAction 字段
    summary: str = ""
    validation: str = ""
    notes: str = ""
    validation_skipped_reason: str = ""

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

    def __init__(
        self,
        summary: str,
        validation: str = "",
        notes: str = "",
        validation_skipped_reason: str = "",
    ):
        super().__init__(is_finish=True)
        self.summary = summary
        self.validation = validation
        self.notes = notes
        self.validation_skipped_reason = validation_skipped_reason


@dataclass
class ToolAction(AgentAction):
    """合法 Tool Action。"""

    def __init__(
        self,
        tool_name: str,
        arguments: dict,
        action_id: str = "",
        raw_response: Any = None,
        preamble: str = "",
    ):
        super().__init__(is_finish=False)
        self.tool_name = tool_name
        self.arguments = arguments
        self.action_id = action_id
        self.raw_response = raw_response
        self.preamble = preamble


@dataclass
class InvalidAction(AgentAction):
    """非法 Action（如模型输出空、未知 tool、参数错误）。"""

    def __init__(self, error_msg: str, *, is_protocol_failure: bool = False):
        super().__init__(is_invalid=True, error_msg=error_msg, is_protocol_failure=is_protocol_failure)


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
    def ok(cls, content: str, **kwargs) -> ToolResult:
        return cls(success=True, content=content, **kwargs)

    @classmethod
    def fail(cls, error: str, **kwargs) -> ToolResult:
        return cls(success=False, content=error, error=error, **kwargs)


# 别名（语义化）
Observation = ToolResult
