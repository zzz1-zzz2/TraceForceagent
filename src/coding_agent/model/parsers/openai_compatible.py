"""OpenAI 兼容 Provider 的 ResponseParser。

把 ModelResponse 归一为 AgentAction：
- ToolAction: 合法 tool 调用
- FinishAction: 显式 finish
- InvalidAction: 非法（unknown tool / 参数错误 / 空响应 / 协议级失败）

注意：题目要求"模型输出解析"自实现。我们从 OpenAI SDK 拿到原始响应后，
自己完成 tool name lookup、schema validation、归一化。SDK 只提供传输协议。

P2-1E.1 (ModelResponseGuard) 增量：
- finish_reason=length / content_filter：明确拒绝执行 tool；
- V1 对多个 Tool Call 明确拒绝（不再静默取第一个）；
- 非法 / 不完整 JSON：明确协议失败，保留有界诊断；
- 文本 + 1 个 Tool Call：把文本作为 preamble 附加到 ToolAction；
- 空响应（无 tool_calls 且无 content）：保留 InvalidAction。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from coding_agent.model.types import (
    AgentAction,
    AssistantReplyAction,
    FinishAction,
    InvalidAction,
    ModelResponse,
    ToolAction,
)

if TYPE_CHECKING:
    # 避免 model ↔ tools 包循环导入
    from coding_agent.tools.registry import ToolRegistry


# 不执行 tool 的 finish_reason（与 SDK 语义对齐：length/content_filter
# 表示模型生成被截断或被内容过滤，结果不完整，直接执行 tool 风险过高）。
_UNSAFE_FINISH_REASONS: frozenset[str] = frozenset({"length", "content_filter"})

# 协议失败诊断文本的最大长度，避免把巨大 raw_arguments / content
# 全部塞进 feedback。
_MAX_DIAGNOSTIC_CHARS = 200


def _bounded(value: str, *, limit: int = _MAX_DIAGNOSTIC_CHARS) -> str:
    """Truncate ``value`` to ``limit`` chars, appending an ellipsis marker."""
    if len(value) <= limit:
        return value
    return value[:limit] + f"…(truncated,{len(value)} chars)"


class OpenAICompatibleParser:
    """把 ModelResponse 解析为 AgentAction。"""

    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def parse(self, response: ModelResponse) -> AgentAction:
        """主入口。

        优先级（P2-1E.1 修订）：
        0. finish_reason=length/content_filter → InvalidAction(协议失败)，
           不进入任何 tool 执行路径；
        1. 空响应（无 tool_calls 且无 content）→ InvalidAction；
        2. 多个 tool_calls → InvalidAction(协议失败)，V1 不支持并行；
        3. 单个 tool_call：先检查 JSON 解析失败 → InvalidAction(协议失败)；
           然后 tool 查找 / schema validation / finish 特殊路径；
        4. 文本 + 1 个 Tool Call：ToolAction.preamble = response.content；
        5. 无 tool、content 非空且 finish_reason=stop：AssistantReplyAction；
        6. 其它纯文本 / 未知终止原因：InvalidAction。

        注意：删除 text-based finish detection（"i'm done" / "i am done" /
        "task completed" / "finished"）。文本匹配会产生大量假阳性（如模型在
        think 时说"not finished yet"），并绕过 FinishPolicy 校验。
        """
        finish_reason = (response.finish_reason or "").strip()

        # 0. finish_reason 截断 / 内容过滤：模型输出不完整，
        #    绝不执行 tool。即使 SDK 给出了 tool_call，也视为不可信。
        if finish_reason in _UNSAFE_FINISH_REASONS:
            return InvalidAction(
                f"Refused to execute: model returned finish_reason={finish_reason!r}; "
                f"response may be truncated or filtered. content_preview="
                f"{_bounded(response.content)}",
                is_protocol_failure=True,
            )

        # 1. 空响应：保留原有 InvalidAction（非协议失败，语义类）。
        if not response.tool_calls and not response.content:
            return InvalidAction("Empty response from model")

        # 2. 多 Tool Call：V1 明确拒绝（不再静默取第一个）。
        if len(response.tool_calls) > 1:
            names = ", ".join(tc.name for tc in response.tool_calls)
            return InvalidAction(
                f"Refused: V1 does not support multiple tool calls in one response; "
                f"received {len(response.tool_calls)} calls: [{names}]",
                is_protocol_failure=True,
            )

        # 3. 单个 tool_call。
        if response.tool_calls:
            tc = response.tool_calls[0]

            # 3a. JSON 解析失败：明确协议失败，保留有界诊断。
            if tc.arguments_parse_error:
                return InvalidAction(
                    f"Refused: tool {tc.name!r} arguments are not valid JSON: "
                    f"{tc.arguments_parse_error}. raw_arguments="
                    f"{_bounded(tc.raw_arguments)}",
                    is_protocol_failure=True,
                )

            tool = self.registry.get(tc.name)
            if tool is None:
                return InvalidAction(f"Unknown tool: {tc.name}")

            # schema validation（委托给 tool 自身）
            errors = tool.validate_args(tc.arguments)
            if errors:
                return InvalidAction(
                    f"Invalid arguments for {tc.name}: {errors}. "
                    f"Received: {tc.arguments}"
                )

            # 特殊处理：finish tool
            if tc.name == "finish":
                return FinishAction(
                    summary=tc.arguments.get("summary", ""),
                    validation=tc.arguments.get("validation", ""),
                    notes=tc.arguments.get("notes", ""),
                    validation_skipped_reason=tc.arguments.get(
                        "validation_skipped_reason", ""
                    ),
                )

            # 4. 文本 + 1 Tool Call：把文本作为 preamble 附加。
            return ToolAction(
                tool_name=tc.name,
                arguments=tc.arguments,
                action_id=tc.id,
                raw_response=response.raw,
                preamble=response.content,
            )

        # 5. 合法普通回答：只有明确 stop 才接受为完整回答。
        if response.content.strip() and finish_reason == "stop":
            return AssistantReplyAction(response.content, raw_response=response.raw)

        # 6. 纯文本但缺少合法 stop 终止原因：不接受为完整回答。
        return InvalidAction(
            f"Model returned text with unsupported finish_reason={finish_reason!r}: "
            f"{_bounded(response.content)}",
            is_protocol_failure=True,
        )
