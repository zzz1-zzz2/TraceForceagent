"""P2-1E.1 ModelResponseGuard 回归测试。

覆盖：
- finish_reason=length / content_filter → InvalidAction(协议失败)，不执行 tool；
- V1 多 Tool Call → InvalidAction(协议失败)，不再静默取第一个；
- arguments JSON 解析失败 → InvalidAction(协议失败)，保留有界诊断；
- 文本 + 1 Tool Call → ToolAction.preamble 携带文本；
- 空响应仍是 InvalidAction（语义类，protocol_failure=False）。

所有 fixture credential-free。
"""

from __future__ import annotations

from coding_agent.model.parsers.openai_compatible import OpenAICompatibleParser
from coding_agent.model.types import (
    FinishAction,
    InvalidAction,
    ModelResponse,
    TokenUsage,
    ToolAction,
    ToolCall,
)
from coding_agent.tools.registry import default_registry


def _parser() -> OpenAICompatibleParser:
    return OpenAICompatibleParser(registry=default_registry())


# ============================================================
# finish_reason gates
# ============================================================


class TestFinishReasonGates:
    """finish_reason=length/content_filter 必须阻止 tool 执行。"""

    def test_length_with_tool_call_is_rejected_as_protocol_failure(self) -> None:
        response = ModelResponse(
            content="partial text before cutoff",
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name="list_files",
                    arguments={"path": "."},
                )
            ],
            finish_reason="length",
            usage=TokenUsage(),
        )
        action = _parser().parse(response)
        assert isinstance(action, InvalidAction)
        assert action.is_invalid
        assert action.is_protocol_failure
        # 关键：不能让 tool 跑到 loop 工具执行分支。
        assert action.tool_name == ""
        # 诊断必须明确包含 finish_reason。
        assert "length" in action.error_msg
        # content_preview 必须有界（不能把整段 huge text 塞进 feedback）。
        assert "partial text before cutoff" in action.error_msg

    def test_content_filter_with_text_only_is_rejected(self) -> None:
        response = ModelResponse(
            content="some filtered content",
            tool_calls=[],
            finish_reason="content_filter",
            usage=TokenUsage(),
        )
        action = _parser().parse(response)
        assert isinstance(action, InvalidAction)
        assert action.is_protocol_failure
        assert "content_filter" in action.error_msg

    def test_length_with_no_content_and_no_tool_is_rejected_not_empty(self) -> None:
        """finish_reason=length 必须先于"空响应"检查命中，避免给出
        误导性的 'Empty response from model'。"""
        response = ModelResponse(
            content="",
            tool_calls=[],
            finish_reason="length",
            usage=TokenUsage(),
        )
        action = _parser().parse(response)
        assert isinstance(action, InvalidAction)
        assert action.is_protocol_failure
        assert "length" in action.error_msg

    def test_stop_finish_reason_is_normal(self) -> None:
        """finish_reason=stop 时不应触发协议失败路径。"""
        response = ModelResponse(
            content="",
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name="list_files",
                    arguments={"path": "."},
                )
            ],
            finish_reason="stop",
            usage=TokenUsage(),
        )
        action = _parser().parse(response)
        assert isinstance(action, ToolAction)
        assert not action.is_protocol_failure


# ============================================================
# Multi-call rejection
# ============================================================


class TestMultiCallRejection:
    """V1 对多个 Tool Call 明确拒绝（不再静默取第一个）。"""

    def test_two_tool_calls_returns_protocol_failure(self) -> None:
        response = ModelResponse(
            content="",
            tool_calls=[
                ToolCall(id="c1", name="list_files", arguments={"path": "."}),
                ToolCall(id="c2", name="read_file", arguments={"path": "x.py"}),
            ],
            finish_reason="tool_calls",
            usage=TokenUsage(),
        )
        action = _parser().parse(response)
        assert isinstance(action, InvalidAction)
        assert action.is_protocol_failure
        # 错误信息应该同时暴露 call 数和 names（便于模型调试）。
        assert "2" in action.error_msg
        assert "list_files" in action.error_msg
        assert "read_file" in action.error_msg

    def test_three_tool_calls_also_rejected(self) -> None:
        response = ModelResponse(
            content="",
            tool_calls=[
                ToolCall(id=f"c{i}", name=f"tool_{i}", arguments={})
                for i in range(3)
            ],
            finish_reason="tool_calls",
            usage=TokenUsage(),
        )
        action = _parser().parse(response)
        assert action.is_protocol_failure
        assert "3" in action.error_msg


# ============================================================
# Invalid JSON
# ============================================================


class TestInvalidJSONArguments:
    """arguments JSON 解析失败 → 明确协议失败，保留有界诊断。"""

    def test_unparseable_arguments_returns_protocol_failure(self) -> None:
        response = ModelResponse(
            content="",
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name="read_file",
                    arguments={},
                    raw_arguments='{"path": ',  # 故意截断
                    arguments_parse_error="Expecting value: line 1 column 10 (char 9)",
                )
            ],
            finish_reason="tool_calls",
            usage=TokenUsage(),
        )
        action = _parser().parse(response)
        assert isinstance(action, InvalidAction)
        assert action.is_protocol_failure
        # 必须包含 parse error 和 tool name。
        assert "Expecting value" in action.error_msg
        assert "read_file" in action.error_msg
        # raw_arguments 也应进入诊断（用于调试）。
        assert "{" in action.error_msg

    def test_diagnostic_is_bounded(self) -> None:
        """巨大 raw_arguments 必须被截断，不能膨胀 feedback。"""
        huge_raw = '{"path": "' + ("x" * 5000) + '"}'
        response = ModelResponse(
            content="",
            tool_calls=[
                ToolCall(
                    id="c1",
                    name="read_file",
                    arguments={},
                    raw_arguments=huge_raw,
                    arguments_parse_error="unterminated string",
                )
            ],
            finish_reason="tool_calls",
            usage=TokenUsage(),
        )
        action = _parser().parse(response)
        assert action.is_protocol_failure
        # 错误消息必须 < 5000 chars（远小于 raw）。
        assert len(action.error_msg) < 1000
        assert "truncated" in action.error_msg


# ============================================================
# Preamble: text + 1 tool call
# ============================================================


class TestPreambleWithSingleToolCall:
    """文本 + 1 Tool Call → ToolAction.preamble 携带文本。"""

    def test_text_plus_tool_call_keeps_preamble(self) -> None:
        response = ModelResponse(
            content="Let me check the project structure first.",
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name="list_files",
                    arguments={"path": "."},
                )
            ],
            finish_reason="tool_calls",
            usage=TokenUsage(),
        )
        action = _parser().parse(response)
        assert isinstance(action, ToolAction)
        assert action.tool_name == "list_files"
        assert action.preamble == "Let me check the project structure first."
        assert not action.is_invalid
        assert not action.is_protocol_failure

    def test_empty_text_plus_tool_call_has_empty_preamble(self) -> None:
        """无文本时 preamble 为空字符串（向后兼容纯 tool 调用）。"""
        response = ModelResponse(
            content="",
            tool_calls=[
                ToolCall(id="c1", name="list_files", arguments={"path": "."}),
            ],
            finish_reason="tool_calls",
            usage=TokenUsage(),
        )
        action = _parser().parse(response)
        assert isinstance(action, ToolAction)
        assert action.preamble == ""

    def test_text_plus_finish_tool_has_no_preamble_attached(self) -> None:
        """finish tool 仍是 FinishAction，文本不被当作 preamble 附加。"""
        response = ModelResponse(
            content="Wrapping up.",
            tool_calls=[
                ToolCall(
                    id="c_f",
                    name="finish",
                    arguments={"summary": "did X", "validation": "passed"},
                )
            ],
            finish_reason="tool_calls",
            usage=TokenUsage(),
        )
        action = _parser().parse(response)
        assert isinstance(action, FinishAction)
        assert action.summary == "did X"


# ============================================================
# Empty response (regression)
# ============================================================


class TestEmptyResponseRegression:
    """空响应仍是 InvalidAction（语义类，非协议失败）。"""

    def test_empty_returns_semantic_invalid(self) -> None:
        response = ModelResponse(content="", tool_calls=[], usage=TokenUsage())
        action = _parser().parse(response)
        assert isinstance(action, InvalidAction)
        assert action.is_invalid
        # 空响应不应被标记为协议失败 — 模型可能因别的原因静默，
        # 标记 protocol_failure 会让 loop 的反馈误导。
        assert not action.is_protocol_failure
        assert "empty" in action.error_msg.lower()

    def test_text_only_returns_semantic_invalid(self) -> None:
        """纯文本（不带 tool_call）仍按 InvalidAction 处理（V1 协议）。"""
        response = ModelResponse(
            content="Just thinking out loud.",
            tool_calls=[],
            finish_reason="stop",
            usage=TokenUsage(),
        )
        action = _parser().parse(response)
        assert isinstance(action, InvalidAction)
        assert action.is_invalid
        assert not action.is_protocol_failure


# ============================================================
# Argument validation (regression)
# ============================================================


class TestArgumentValidationRegression:
    """schema validation 失败仍走语义 InvalidAction（非协议失败）。"""

    def test_wrong_type_args_returns_semantic_invalid(self) -> None:
        response = ModelResponse(
            content="",
            tool_calls=[
                ToolCall(
                    id="c1",
                    name="read_file",
                    arguments={"path": [123, 456]},
                    raw_arguments="{}",
                )
            ],
            finish_reason="tool_calls",
            usage=TokenUsage(),
        )
        action = _parser().parse(response)
        assert isinstance(action, InvalidAction)
        assert action.is_invalid
        # schema-level 错误是语义失败，不是协议失败。
        assert not action.is_protocol_failure

    def test_unknown_tool_returns_semantic_invalid(self) -> None:
        response = ModelResponse(
            content="",
            tool_calls=[
                ToolCall(id="c1", name="nope", arguments={}, raw_arguments="{}"),
            ],
            finish_reason="tool_calls",
            usage=TokenUsage(),
        )
        action = _parser().parse(response)
        assert isinstance(action, InvalidAction)
        assert action.is_invalid
        assert not action.is_protocol_failure


# ============================================================
# ToolCall.arguments_parse_error plumbing
# ============================================================


class TestToolCallPlumbing:
    """ToolCall 必须能承载 arguments_parse_error。"""

    def test_default_is_none(self) -> None:
        tc = ToolCall(id="x", name="y", arguments={})
        assert tc.arguments_parse_error is None

    def test_can_carry_parse_error(self) -> None:
        tc = ToolCall(
            id="x",
            name="y",
            arguments={},
            raw_arguments="broken",
            arguments_parse_error="bad json",
        )
        assert tc.arguments_parse_error == "bad json"
