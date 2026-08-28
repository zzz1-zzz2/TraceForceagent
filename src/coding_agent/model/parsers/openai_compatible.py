"""OpenAI 兼容 Provider 的 ResponseParser。

把 ModelResponse 归一为 AgentAction：
- ToolAction: 合法 tool 调用
- FinishAction: 显式 finish
- InvalidAction: 非法（unknown tool / 参数错误 / 空响应）

注意：题目要求"模型输出解析"自实现。我们从 OpenAI SDK 拿到原始响应后，
自己完成 tool name lookup、schema validation、归一化。SDK 只提供传输协议。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from coding_agent.model.types import (
    AgentAction,
    FinishAction,
    InvalidAction,
    ModelResponse,
    ToolAction,
)

if TYPE_CHECKING:
    # 避免 model ↔ tools 包循环导入
    from coding_agent.tools.registry import ToolRegistry


class OpenAICompatibleParser:
    """把 ModelResponse 解析为 AgentAction。"""

    def __init__(self, registry: "ToolRegistry"):
        self.registry = registry

    def parse(self, response: ModelResponse) -> AgentAction:
        """主入口。

        优先级：
        1. 多个 tool_calls：取第一个（V1 不支持并行）
        2. 单个 tool_call：解析为 ToolAction 或 FinishAction（finish 是普通 tool）
        3. 都没有：InvalidAction

        注意：删除 text-based finish detection（"i'm done" / "i am done" /
        "task completed" / "finished"）。文本匹配会产生大量假阳性（如模型在
        think 时说"not finished yet"），并绕过 FinishPolicy 校验。
        """
        if not response.tool_calls and not response.content:
            return InvalidAction("Empty response from model")

        if response.tool_calls:
            tc = response.tool_calls[0]
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

            return ToolAction(
                tool_name=tc.name,
                arguments=tc.arguments,
                action_id=tc.id,
                raw_response=response.raw,
            )

        # 模型在 content 里写了纯文本（不是 tool call）：
        # 在 V1 policy 下视为 InvalidAction。让 AgentLoop 通过 record_feedback
        # 告知模型"必须用 tool call"。
        return InvalidAction(
            f"Model returned text instead of tool call: {response.content[:200]}"
        )