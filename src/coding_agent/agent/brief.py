"""TaskBrief：结构化任务描述。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TaskMode(str, Enum):
    EXISTING_REPOSITORY = "existing_repository"
    GREENFIELD = "greenfield"


@dataclass
class TaskBrief:
    """结构化任务描述。

    与 original_task 的区别：
    - original_task 是 source of truth（事实）
    - TaskBrief 是 operational representation（程序可用结构）
    """

    goal: str
    constraints: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    task_mode: TaskMode = TaskMode.EXISTING_REPOSITORY

    def to_text(self) -> str:
        """转成可注入 messages 的文本。"""
        lines = [
            f"Goal: {self.goal}",
        ]
        if self.constraints:
            lines.append("Constraints:")
            for c in self.constraints:
                lines.append(f"  - {c}")
        if self.success_criteria:
            lines.append("Success Criteria:")
            for s in self.success_criteria:
                lines.append(f"  - {s}")
        if self.unknowns:
            lines.append("Unknowns:")
            for u in self.unknowns:
                lines.append(f"  - {u}")
        lines.append(f"Task Mode: {self.task_mode.value}")
        return "\n".join(lines)

    @classmethod
    def from_user_task(cls, task: str, task_mode: TaskMode | None = None) -> "TaskBrief":
        """从用户原始输入构造。

        V1 简化版：goal = 整段 task，其他字段留空。
        后续可让 LLM 在第一轮帮忙结构化。
        """
        if task_mode is None:
            # 简单启发式：包含 "create" / "implement" / "build" / "new" → greenfield
            lowered = task.lower()
            if any(kw in lowered for kw in ["create", "implement", "build", "new", "from scratch"]):
                task_mode = TaskMode.GREENFIELD
            else:
                task_mode = TaskMode.EXISTING_REPOSITORY

        return cls(
            goal=task,
            task_mode=task_mode,
        )