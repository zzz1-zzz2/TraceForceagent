"""TerminationController：判断循环是否应停止。"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from coding_agent.agent.state import AgentState, StopReason


@dataclass
class TerminationConfig:
    """终止阈值配置。"""

    max_steps: int = 50
    max_model_calls: int = 80
    max_wall_time: int = 1800  # 秒
    max_consecutive_errors: int = 5
    max_consecutive_timeouts: int = 3
    repeated_action_limit: int = 3  # 相同动作连续 N 次未获新信息
    stagnation_limit: int = 8  # 连续 N 步无进展


class TerminationController:
    """循环终止控制器。

    设计原则：
    - 不要擅自终止：先返回 feedback 给模型一次，再终止
    - 多重防线：6 类阈值 + stagnation detector
    """

    def __init__(self, config: TerminationConfig):
        self.config = config
        # 跟踪每个 action 的连续出现次数（用 normalized key）
        self._action_streaks: Counter = Counter()

    def record_action(self, tool_name: str, args_hash: str, observation_changed: bool) -> None:
        """记录一次 action 与其 observation 是否带来新信息。"""
        key = f"{tool_name}:{args_hash}"
        if observation_changed:
            # 有新信息，重置计数
            self._action_streaks[key] = 0
            # 同时重置所有 streaks（因为模型在进步）
            self._action_streaks.clear()
        else:
            self._action_streaks[key] += 1

    def should_stop(self, state: AgentState) -> tuple[bool, StopReason | None, str | None]:
        """判断是否应该停止。

        Returns:
            (should_stop, stop_reason, feedback_message)
            feedback_message 不为空时表示"建议停止但先给模型一次反馈"
        """
        cfg = self.config

        # 1. 步数限制
        if state.step_count >= cfg.max_steps:
            return True, StopReason.MAX_STEPS, None

        # 2. 模型调用限制
        if state.model_calls >= cfg.max_model_calls:
            return True, StopReason.MAX_MODEL_CALLS, None

        # 3. 时间限制
        if state.elapsed_seconds() >= cfg.max_wall_time:
            return True, StopReason.MAX_WALL_TIME, None

        # 4. 连续错误
        if state.consecutive_errors >= cfg.max_consecutive_errors:
            return True, StopReason.MAX_CONSECUTIVE_ERRORS, None

        # 5. 连续超时
        if state.consecutive_timeouts >= cfg.max_consecutive_timeouts:
            return True, StopReason.MAX_CONSECUTIVE_TIMEOUTS, None

        # 6. 重复动作
        if self._action_streaks:
            top_key, top_count = self._action_streaks.most_common(1)[0]
            if top_count >= cfg.repeated_action_limit:
                return True, StopReason.REPEATED_ACTION, None

        # 7. Stagnation：连续 N 步状态完全没变
        if state.is_stagnant(lookback=cfg.stagnation_limit):
            return True, StopReason.STAGNATION, None

        return False, None, None

    def get_repeated_action_feedback(self) -> str | None:
        """如果存在重复动作但还没到终止阈值，返回建议。"""
        if not self._action_streaks:
            return None
        top_key, top_count = self._action_streaks.most_common(1)[0]
        if top_count >= 2:  # 连续 2 次就给反馈
            return (
                f"你已经连续 {top_count} 次调用 {top_key.split(':')[0]} "
                f"且没有获得新信息。请改变策略：尝试不同的 tool、参数或思路。"
            )
        return None