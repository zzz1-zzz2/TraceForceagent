"""TaskBrief：结构化任务描述。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


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
        lines = [f"Goal: {self.goal}"]
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
    def from_user_task(
        cls,
        task: str,
        task_mode: TaskMode | str | None = None,
        workspace: Path | None = None,
    ) -> "TaskBrief":
        """从用户原始输入构造。

        Explicit ``task_mode`` is authoritative. Without it, Greenfield is
        inferred only from clear creation intent in an empty workspace; a
        non-empty workspace remains an existing repository by default.
        """
        if task_mode is None:
            task_mode = detect_task_mode(task, workspace)
        elif isinstance(task_mode, str):
            task_mode = TaskMode(task_mode)

        return cls(goal=task, task_mode=task_mode)


def workspace_is_empty(workspace: Path | None) -> bool:
    """Return whether a workspace has no meaningful user files.

    A checkout's ``.git`` directory is metadata, not project content. Missing
    or not-yet-created workspaces are treated as empty so CLI callers can build
    a project in a new directory.
    """
    if workspace is None:
        return False
    try:
        if not workspace.exists():
            return True
        if not workspace.is_dir():
            return False
        return not any(path.name != ".git" for path in workspace.iterdir())
    except OSError:
        return False


def has_greenfield_intent(task: str) -> bool:
    """Recognize explicit project-creation language, not generic coding verbs."""
    lowered = task.lower()
    strong_phrases = (
        "from scratch",
        "from zero",
        "scaffold",
        "skeleton",
        "boilerplate",
        "empty project",
        "new project",
        "create a website",
        "create a web site",
        "create a cli",
        "create an app",
        "build a website",
        "build a web site",
        "build a cli",
        "write a website",
        "write a web site",
        "写一个网站",
        "做一个网站",
        "创建一个网站",
        "搭建一个网站",
        "写一个项目",
        "做一个项目",
        "创建一个项目",
        "新建项目",
        "从头开始",
        "从零开始",
        "从头构建",
        "从零构建",
        "项目骨架",
    )
    return any(phrase in lowered for phrase in strong_phrases)


def detect_task_mode(task: str, workspace: Path | None = None) -> TaskMode:
    """Infer task mode using workspace state plus strong user intent."""
    if workspace_is_empty(workspace) and has_greenfield_intent(task):
        return TaskMode.GREENFIELD
    return TaskMode.EXISTING_REPOSITORY
