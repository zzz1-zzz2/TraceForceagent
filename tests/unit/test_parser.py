"""Parser 单元测试：合法 / 非法 / 未知 tool / finish 信号。"""

import pytest

from coding_agent.model.parsers.openai_compatible import OpenAICompatibleParser
from coding_agent.model.types import (
    FinishAction,
    AssistantReplyAction,
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
    def test_stop_text_is_assistant_reply(self):
        action = make_parser().parse(ModelResponse(
            content="你好，我是 TraceForce。",
            finish_reason="stop",
            usage=TokenUsage(),
        ))
        assert isinstance(action, AssistantReplyAction)
        assert action.reply_text == "你好，我是 TraceForce。"

    @pytest.mark.parametrize("finish_reason", ["length", "content_filter", ""])
    def test_incomplete_text_is_not_accepted(self, finish_reason):
        action = make_parser().parse(ModelResponse(
            content="回答未完成",
            finish_reason=finish_reason,
            usage=TokenUsage(),
        ))
        assert isinstance(action, InvalidAction)


    def test_text_response_without_tool_call(self):
        """模型只输出普通文本（不带 tool_call）→ InvalidAction。
        旧版本会把 'I'm done' / 'finished' 等文本识别为 finish 信号，
        但这是高假阳性路径（think 阶段的 'not finished yet' 会被误判），
        V1 已删除。
        """
        parser = make_parser()
        response = ModelResponse(
            content="Let me think about this task carefully.",
            tool_calls=[],
            usage=TokenUsage(),
        )
        action = parser.parse(response)
        assert isinstance(action, InvalidAction)
        assert not action.is_finish

    def test_text_saying_done_is_not_finish(self):
        """回归：'I'm done' / 'task completed' / 'finished' 等文本
        不再被识别为 finish。模型必须显式调用 finish tool。
        """
        parser = make_parser()
        for text in [
            "I'm done with the analysis.",
            "I am done now.",
            "Task completed successfully.",
            "Finished implementing the feature.",
            "Not finished yet, still working.",
            "I'll be finished soon.",
        ]:
            response = ModelResponse(content=text, tool_calls=[], usage=TokenUsage())
            action = parser.parse(response)
            assert not action.is_finish, (
                f"text '{text}' should NOT trigger FinishAction; "
                f"got {type(action).__name__}"
            )
            assert action.is_invalid


class TestNoTextFinishSignal:
    """text-based finish detection 已删除（见 TestTextOnlyResponse 注释）。"""

    def test_old_text_finish_signal_no_longer_triggers(self):
        parser = make_parser()
        response = ModelResponse(
            content="I'm done. The task is finished.",
            tool_calls=[],
            usage=TokenUsage(),
        )
        action = parser.parse(response)
        assert not isinstance(action, FinishAction)
        assert action.is_invalid