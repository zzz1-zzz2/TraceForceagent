"""OpenAI 兼容 Provider 的 ResponseParser。

把 ModelResponse 归一为 AgentAction：
- ToolAction: 合法 tool 调用
- FinishAction: 显式 finish
- InvalidAction: 非法（unknown tool / 参数错误 / 空响应）

注意：题目要求"模型输出解析"自实现。我们从 OpenAI SDK 拿到原始响应后，
自己完成 tool name lookup、schema validation、归一化。SDK 只提供传输协议。
"""

from __future__ import annotations

from coding_agent.model.types import (
    AgentAction,
    FinishAction,
    InvalidAction,
    ModelResponse,
    ToolAction,
)
from coding_agent.tools.registry import ToolRegistry


class OpenAICompatibleParser:
    """把 ModelResponse 解析为 AgentAction。"""

    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def parse(self, response: ModelResponse) -> AgentAction:
        """主入口。

        优先级：
        1. 多个 tool_calls：取第一个（V1 不支持并行）
        2. 单个 tool_call：解析为 ToolAction
        3. content 含 finish 信号（罕见）：解析为 FinishAction
        4. 都没有：InvalidAction
        """
        if not response.tool_calls and not response.content:
            return InvalidAction("Empty response from model")

        # 处理 finish tool（OpenAI 兼容 provider 通过 finish tool 实现）
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
                )

            return ToolAction(
                tool_name=tc.name,
                arguments=tc.arguments,
                action_id=tc.id,
                raw_response=response.raw,
            )

        # 如果模型在 content 里说 "I'm done"，转换为提示信息
        content = response.content.lower()
        if any(signal in content for signal in ["i'm done", "i am done", "task completed", "finished"]):
            return FinishAction(
                summary=response.content,
                validation="(no explicit validation)",
                notes="Detected via text signal (not via finish tool)",
            )

        return InvalidAction(
            f"Model returned text instead of tool call: {response.content[:200]}"
        )