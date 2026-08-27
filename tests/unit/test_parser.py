"""Parser 单元测试：合法 / 非法 / 未知 tool / finish 信号。"""

import pytest

from coding_agent.model.parsers.openai_compatible import OpenAICompatibleParser
from coding_agent.model.types import (
    FinishAction,
    InvalidAction,
    ModelResponse,
    TokenUsage,
    ToolCall,
)
from coding_agent.tools.registry import default_registry


def make_parser() -> OpenAICompatibleParser:
    return OpenAICompatibleParser(registry=default_registry())


class TestValidToolCall:
    def test_known_tool_with_valid_args(self):
        """合法 tool call 解析为 ToolAction。"""
        parser = make_parser()
        response = ModelResponse(
            content="",
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name="list_files",
                    arguments={"path": "."},
                    raw_arguments='{"path": "."}',
                )
            ],
            usage=TokenUsage(),
        )
        action = parser.parse(response)
        from coding_agent.model.types import ToolAction

        assert isinstance(action, ToolAction)
        assert action.tool_name == "list_files"
        assert action.arguments == {"path": "."}
        assert not action.is_finish
        assert not action.is_invalid


class TestFinishTool:
    def test_finish_tool_call(self):
        """finish tool 解析为 FinishAction。"""
        parser = make_parser()
        response = ModelResponse(
            content="",
            tool_calls=[
                ToolCall(
                    id="call_f",
                    name="finish",
                    arguments={"summary": "did X", "validation": "pytest passed"},
                    raw_arguments="{}",
                )
            ],
            usage=TokenUsage(),
        )
        action = parser.parse(response)
        assert isinstance(action, FinishAction)
        assert action.summary == "did X"
        assert action.validation == "pytest passed"
        assert action.is_finish


class TestUnknownTool:
    def test_unknown_tool_returns_invalid(self):
        """未知 tool 名应该返回 InvalidAction，而不是崩。"""
        parser = make_parser()
        response = ModelResponse(
            content="",
            tool_calls=[
                ToolCall(
                    id="call_x",
                    name="definitely_not_a_tool",
                    arguments={},
                    raw_arguments="{}",
                )
            ],
            usage=TokenUsage(),
        )
        action = parser.parse(response)
        assert isinstance(action, InvalidAction)
        assert "definitely_not_a_tool" in action.error_msg
        assert action.is_invalid


class TestInvalidArgs:
    def test_wrong_type_args_returns_invalid(self):
        """参数类型错误应返回 InvalidAction。"""
        parser = make_parser()
        # read_file 要求 path 是 string, 这里给 list
        response = ModelResponse(
            content="",
            tool_calls=[
                ToolCall(
                    id="call_x",
                    name="read_file",
                    arguments={"path": [123, 456]},  # 错类型
                    raw_arguments="{}",
                )
            ],
            usage=TokenUsage(),
        )
        action = parser.parse(response)
        assert isinstance(action, InvalidAction)
        assert "path" in action.error_msg.lower()


class TestEmptyResponse:
    def test_empty_response_returns_invalid(self):
        """空响应应该返回 InvalidAction。"""
        parser = make_parser()
        response = ModelResponse(content="", tool_calls=[], usage=TokenUsage())
        action = parser.parse(response)
        assert isinstance(action, InvalidAction)
        assert "empty" in action.error_msg.lower()


class TestTextOnlyResponse:
    def test_text_response_without_finish_signal(self):
        """模型只输出普通文本（不包含 finish 信号）→ InvalidAction。"""
        parser = make_parser()
        response = ModelResponse(
            content="Let me think about this task carefully.",
            tool_calls=[],
            usage=TokenUsage(),
        )
        action = parser.parse(response)
        assert isinstance(action, InvalidAction)
        assert not action.is_finish


class TestTextFinishSignal:
    def test_text_finish_signal_in_english(self):
        """文本包含 'i'm done' 等英文 finish 信号 → FinishAction。"""
        parser = make_parser()
        response = ModelResponse(
            content="I'm done. The task is finished.",
            tool_calls=[],
            usage=TokenUsage(),
        )
        action = parser.parse(response)
        assert isinstance(action, FinishAction)