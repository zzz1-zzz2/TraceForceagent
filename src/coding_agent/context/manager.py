"""ContextManager：构造 Active Context。

五段式：
1. System Prompt
2. Original Task（P0，永远保留）
3. Task Brief（P1）
4. Working State（P1）
5. Recent Interaction（P2，可淘汰）

Full Trajectory 由 TrajectoryLogger 单独保存，与 Active Context 解耦。

P0–P3 优先级淘汰：当 token 数接近 context_budget 时，按优先级从低到高裁剪。
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from typing import Any

import tiktoken

from coding_agent.agent.brief import TaskBrief
from coding_agent.agent.state import AgentState
from coding_agent.config import AgentConfig
from coding_agent.context.working_state import WorkingStateBuilder
from coding_agent.model.types import ToolResult


_log = logging.getLogger(__name__)


@dataclass
class _RecentTurn:
    """一对 (assistant, tool_result) 称为一个 turn。"""

    assistant_content: str
    tool_call_id: str
    tool_call_name: str
    tool_call_args: dict
    tool_result_content: str
    tool_result_success: bool


@dataclass
class _TurnBundle:
    """一个 tool turn 的不可拆分 bundle：(assistant tool_call, tool_result)。

    预算裁剪时作为一个整体处理：要么两条都进，要么两条都不进。
    防止出现 orphan assistant tool_call 破坏 OpenAI tool calling 的不变量。
    """

    assistant: dict
    tool: dict


class ContextManager:
    """管理 Active Context 的构造与裁剪。

    关键设计：
    - record_observation 只能用于"真实发生的 tool 调用"对应的 (assistant, tool) turn。
    - record_feedback 用于"需要告诉模型某事、但不是因为真实 tool 执行"的场景
      （如 InvalidAction、Finish Policy 拒绝等）。
      feedback 作为 P0 消息注入，永不被裁剪；并且不构造 fake tool_call_id。
    """

    SYSTEM_PROMPT = """You are a coding agent. You autonomously complete software engineering tasks.

You have access to these tools:
- list_files(path, max_depth): browse directory structure
- read_file(path, start_line, end_line): read file content (default 200-line window)
- search_code(query, path, max_results): search for symbols/text using ripgrep
- apply_patch(path, old_string, new_string) OR apply_patch(path, content, mode="create"): modify/create/delete files
- run_command(command, cwd, timeout): execute shell command (independent subprocess, no persistent shell)
- git_diff(): show current changes
- update_plan(items): maintain your multi-step plan (visible in TUI)
- finish(summary, validation, notes): explicitly submit your work when done

Rules:
1. Read existing code before modifying it.
2. Run tests after every change to verify.
3. Use apply_patch with surgical edits, not full-file overwrites.
4. Don't repeat the same action without new information — if stuck, change strategy.
5. Always call finish() when done, with summary + validation. Don't end with just text.

Workspace path boundary: You cannot escape the workspace directory."""

    def __init__(self, config: AgentConfig):
        self.config = config
        self.working_state_builder = WorkingStateBuilder()
        self._recent_turns: deque[_RecentTurn] = deque(maxlen=config.recent_turns * 2)
        # 高优先级反馈（如 InvalidAction、FinishPolicy 拒绝）。
        # 与 record_observation 互斥：feedback 不构造 fake tool message。
        self._feedback: deque[str] = deque(maxlen=10)
        # tiktoken encoder (cl100k_base 是 GPT-4/DeepSeek 通用)
        try:
            self._enc = tiktoken.get_encoding("cl100k_base")
        except Exception:
            # fallback：粗略按字符数估算
            _log.warning("tiktoken cl100k_base 加载失败，使用字符数估算")
            self._enc = None

    def _count_tokens(self, text: str) -> int:
        """计算 token 数。tiktoken 不可用时按字符数 /4 估算。"""
        if self._enc:
            return len(self._enc.encode(text))
        return max(1, len(text) // 4)

    def _count_message_tokens(self, msg: dict) -> int:
        """计算单条 message 的 token（content + role 等开销）。"""
        text = msg.get("content", "") or ""
        if msg.get("role") == "tool":
            # tool 消息还有 tool_call_id
            text += str(msg.get("tool_call_id", ""))
        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                fn = tc.get("function", {})
                text += fn.get("name", "") + fn.get("arguments", "")
        # 消息结构开销约 4 tokens
        return self._count_tokens(text) + 4

    def build(self, state: AgentState, brief: TaskBrief) -> list[dict[str, Any]]:
        """构造完整 Active Context messages，按 token 预算裁剪。"""
        # 1) 构造候选 messages（按优先级标记）
        candidates: list[tuple[str, dict]] = []  # (priority, message)

        # P0: System Prompt
        candidates.append(("P0", {"role": "system", "content": self.SYSTEM_PROMPT}))

        # P0: Feedback（高优先级，永远保留；用于 InvalidAction / FinishPolicy 拒绝等）
        # 注意：每条 feedback 必须是完整自包含的，让模型在新一轮知道该改什么。
        for fb in self._feedback:
            candidates.append(("P0", {"role": "user", "content": fb}))

        # P0: Original Task
        candidates.append(("P0", {"role": "user", "content": f"# Task\n{state.original_task}"}))

        # P1: Task Brief
        candidates.append(("P1", {"role": "assistant", "content": brief.to_text()}))

        # P1: Working State（每次重渲染）
        working_text = self.working_state_builder.render(state)
        if working_text != "(no state yet)":
            candidates.append(("P1", {"role": "user", "content": working_text}))

        # P1: ready_to_finish hint (P1-3 修复)
        # 当最近一次 validation 通过且之后没有新 mutation 时,
        # 注入一条一次性提示,告诉模型"测试已经通过,可以直接 finish"。
        # 优先级 P1：不会被预算裁剪掉,模型下一轮决策时一定能看见。
        if state.ready_to_finish:
            candidates.append(("P1", {
                "role": "user",
                "content": (
                    "[System Hint] The most recent validation passed. "
                    "You should call finish(summary, validation) now, "
                    "with validation describing what passed (e.g. "
                    "'pytest tests/ - 3 passed'). Do NOT run more read_file "
                    "or git_diff unless you have made new changes."
                ),
            }))

        # P2: Recent Interaction（按添加顺序，前面的较低优先级）
        # 关键修复 (P1-4)：tool turn = (assistant tool_call, tool_result) 是一对
        # 不可拆分的单元。必须两条都进入 Context，或两条都淘汰。
        # 否则保留 orphan assistant tool_call 会破坏 OpenAI tool calling 的不变量。
        recent = list(self._recent_turns)[-self.config.recent_turns:]
        for idx, turn in enumerate(recent):
            # 越近的越优先 P2，越远的降为 P3
            priority = "P2" if idx >= len(recent) - 3 else "P3"
            # 把一个 turn 包成 list[tuple[prio, msg]]，后面整体计算 token
            candidates.append((priority, _TurnBundle(
                assistant=(
                    {
                        "role": "assistant",
                        "content": turn.assistant_content or "",
                        "tool_calls": [
                            {
                                "id": turn.tool_call_id,
                                "type": "function",
                                "function": {
                                    "name": turn.tool_call_name,
                                    "arguments": _json_dumps(turn.tool_call_args),
                                },
                            }
                        ],
                    }
                ),
                tool=(
                    {
                        "role": "tool",
                        "tool_call_id": turn.tool_call_id,
                        "content": turn.tool_result_content,
                    }
                ),
            )))

        # 2) 按 token 预算淘汰
        messages = self._pack_by_budget(candidates)

        return messages

    def _pack_by_budget(
        self, candidates: list[tuple[str, Any]]
    ) -> list[dict[str, Any]]:
        """按优先级打包，**硬保证**总 token 数不超过 budget。

        设计要点：
        - 优先级 P0 > P1 > P2 > P3，按出现顺序累加
        - 每一条消息都精确计数；超过 budget 的非 P0 消息**跳过**
        - P0 消息（system / task / feedback）**永不丢弃**——单条超过 budget
          时打 warning 并截断内容，但仍保留
        - 这是 hard cap：返回的消息总 token 数 <= context_budget（除 P0 截断 case）

        Turn bundle 处理 (P1-4 修复)：
        - `_TurnBundle` 是一个 (assistant, tool) 对，打包成 list 提交预算
        - bundle 总 token = assistant_token + tool_token + 4 (overhead)
        - 任一条单独算都超 budget 时，bundle 一起丢，不留 orphan assistant

        与旧版区别：
        - 旧版 "80% 阈值" 魔法数被删除
        - 旧版 P2 用 break 会跳过 P3，现在按顺序公平累加
        - 旧版 P0/P1 全装（可能爆 budget），现在 P1 受 budget 限制
        """
        budget = self.config.context_budget
        total = 0
        selected: list[dict] = []

        for prio, payload in candidates:
            # Turn bundle: 整对一起算 token，一起进 / 一起丢
            if isinstance(payload, _TurnBundle):
                bundle_msgs = [payload.assistant, payload.tool]
                bundle_tok = sum(self._count_message_tokens(m) for m in bundle_msgs)
                if total + bundle_tok > budget:
                    _log.debug(
                        f"ContextManager: dropping turn bundle "
                        f"({bundle_tok} tokens would exceed {total}/{budget})"
                    )
                    continue
                total += bundle_tok
                selected.extend(bundle_msgs)
                continue

            # 普通单条 message
            msg = payload
            tok = self._count_message_tokens(msg)
            if total + tok > budget:
                if prio == "P0":
                    # P0 不能丢：截断到剩余 budget 后保留
                    remaining = max(1, budget - total)
                    _log.warning(
                        f"ContextManager: P0 message alone ({tok} tokens) "
                        f"exceeds remaining budget ({total}/{budget}). "
                        f"Truncating to {remaining} tokens."
                    )
                    msg = self._truncate_message_to_budget(msg, remaining)
                    tok = self._count_message_tokens(msg)
                    if tok > remaining:
                        # 即使截断也超（极少见：仅 message overhead 太多）—— still 放入
                        _log.warning(
                            f"ContextManager: truncated P0 still {tok} > "
                            f"remaining {remaining}; will overflow budget"
                        )
                else:
                    _log.debug(
                        f"ContextManager: skipping {prio} message "
                        f"({tok} tokens would exceed {total}/{budget})"
                    )
                    continue
            total += tok
            selected.append(msg)

        # 强约束：除 P0 截断外，总 token 必须 <= budget
        if total > budget:
            _log.warning(
                f"ContextManager: final total {total} > budget {budget} "
                f"(due to P0 retention; this is acceptable)"
            )

        _log.info(
            f"ContextManager: packed {len(selected)}/{len(candidates)} messages, "
            f"{total}/{budget} tokens"
        )
        return selected

    def _truncate_message_to_budget(self, msg: dict, budget: int) -> dict:
        """截断单条 message 的 content 使其 token 数 <= budget。

        budget 是该消息**整体**的预算（含 4 token message overhead）。
        content 截断目标 = budget - 4。

        仅在 P0 消息单条超过剩余 budget 时调用——罕见（system / task / feedback
        通常远小于 budget）。截断是保底策略，避免完全丢失。
        """
        import copy

        msg = copy.deepcopy(msg)
        content = msg.get("content", "")
        if not isinstance(content, str):
            return msg

        # 给 message overhead 留余量
        content_budget = max(0, budget - 4)

        # 二分查找最长可保留前缀
        lo, hi = 0, len(content)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            tok = self._count_tokens(content[:mid])
            if tok <= content_budget:
                lo = mid
            else:
                hi = mid - 1
        truncated = content[:lo]
        msg["content"] = (
            truncated + "\n\n[... truncated by ContextManager ...]"
            if truncated
            else "[... message exceeded budget; content dropped ...]"
        )
        return msg

    def record_observation(
        self,
        state: AgentState,
        action,  # ToolAction
        observation: ToolResult,
    ) -> None:
        """记录一个 turn 到 Recent Interaction。"""
        self._recent_turns.append(_RecentTurn(
            assistant_content="",
            tool_call_id=action.action_id or "",
            tool_call_name=action.tool_name,
            tool_call_args=action.arguments,
            tool_result_content=observation.content[: self.config.max_tool_output],
            tool_result_success=observation.success,
        ))

    def record_feedback(self, content: str) -> None:
        """记录一条高优先级反馈（不构造 fake tool message）。

        用于：
        - InvalidAction：解析失败（empty response / unknown tool / invalid args）
        - Finish Policy 拒绝：模型试图 finish 但未通过校验
        - 其它需要告诉模型"下一步该做什么"的场景

        与 record_observation 的关键区别：
        - 不构造 (assistant, tool_call_id) → tool 消息对
        - 直接作为 user message 注入 Active Context
        - 优先级为 P0，永远不被裁剪

        Args:
            content: 反馈内容。应当自包含、明确告诉模型下一步动作。
        """
        if content and content.strip():
            self._feedback.append(content.strip())


def _json_dumps(obj: Any) -> str:
    """安全 JSON dump。"""
    import json

    try:
        return json.dumps(obj, ensure_ascii=False)
    except (TypeError, ValueError):
        return "{}"