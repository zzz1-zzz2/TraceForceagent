"""FinishPolicy：校验 FinishAction 是否可被接受。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from coding_agent.agent.state import AgentState
from coding_agent.model.types import FinishAction, ToolResult


@dataclass
class ValidationVerdict:
    """对单次 run_command 调用的分类结果。"""

    is_validation: bool
    passed: bool | None
    reason: str


@dataclass(frozen=True)
class ValidationRequirements:
    """当前工作区完成任务所能提供的验证能力。"""

    has_test_entrypoint: bool
    has_executable_check: bool
    static_only: bool
    static_task: bool
    reason: str

    @property
    def requires_execution(self) -> bool:
        """代码或测试项目必须执行至少一个可识别的检查。"""
        return self.has_test_entrypoint or self.has_executable_check


def classify_validation(observation: ToolResult, command: str) -> ValidationVerdict:
    """判断一次 run_command 调用是否构成 validation run。

    RunCommandTool.is_test_command 是命令分类的单一来源；它现在也覆盖
    build、syntax、type-check、lint 和 smoke/check 命令。
    """
    from coding_agent.tools.shell import RunCommandTool

    if not RunCommandTool.is_test_command(command):
        return ValidationVerdict(
            is_validation=False,
            passed=None,
            reason=f"command '{command[:60]}' is not a validation command",
        )

    if observation.is_runtime_error:
        return ValidationVerdict(
            is_validation=False,
            passed=None,
            reason=f"runtime error: {observation.error[:100] if observation.error else 'unknown'}",
        )

    if observation.is_validation_failure or not observation.success:
        return ValidationVerdict(
            is_validation=True,
            passed=False,
            reason=observation.summary or "validation command failed",
        )
    return ValidationVerdict(
        is_validation=True,
        passed=True,
        reason=observation.summary or "validation command passed",
    )


_TEST_MARKERS = {
    "pytest.ini",
    "tox.ini",
    "noxfile.py",
    "pytest.toml",
}
_TEST_DIRS = {"tests", "test", "__tests__"}
_STATIC_SUFFIXES = {
    ".adoc", ".css", ".html", ".htm", ".markdown", ".md", ".rst", ".svg", ".txt"
}
_CODE_SUFFIXES = {
    ".c", ".cc", ".cpp", ".go", ".java", ".js", ".jsx", ".mjs", ".py", ".rb",
    ".rs", ".sh", ".ts", ".tsx", ".vue",
}
_IGNORED_DIRS = {
    "__pycache__", ".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
}


def _workspace_files(workspace: Path) -> list[Path]:
    """读取有限的工作区清单；坏链接或权限错误不应阻塞 finish policy。"""
    if not workspace.exists() or not workspace.is_dir():
        return []
    files: list[Path] = []
    try:
        for path in workspace.rglob("*"):
            if any(part in _IGNORED_DIRS for part in path.parts):
                continue
            try:
                if path.is_file():
                    files.append(path)
            except OSError:
                continue
    except OSError:
        return []
    return files


def _has_marker(files: list[Path], names: set[str]) -> bool:
    return any(path.name.lower() in names for path in files)


def _contains_text(files: list[Path], needles: tuple[str, ...]) -> bool:
    for path in files:
        if path.name not in {"pyproject.toml", "setup.cfg", "package.json", "Makefile"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        if any(needle in text for needle in needles):
            return True
    return False


def validation_requirements(state: AgentState) -> ValidationRequirements:
    """Infer whether the current Greenfield output has an executable check.

    This is intentionally conservative: absence of tests is not evidence that
    validation can be skipped. A skip is reserved for static/document-only output.
    """
    files = _workspace_files(state.workspace)
    workspace = state.workspace.resolve()
    names = {path.name.lower() for path in files}
    dirs = {
        part.lower()
        for path in files
        for part in path.relative_to(workspace).parts[:-1]
    }
    has_tests = bool(dirs & _TEST_DIRS) or bool(names & _TEST_MARKERS)
    has_tests = has_tests or _contains_text(
        files, ("[tool.pytest", "npm test", "pytest", "tox", "nox")
    )

    source_files = [path for path in files if path.suffix.lower() in _CODE_SUFFIXES]
    has_build = bool(
        names & {"makefile", "dockerfile", "cargo.toml", "go.mod", "pom.xml", "build.gradle"}
    ) or _contains_text(
        files,
        ("npm run build", '"build"', "[tool.ruff", "mypy", "eslint", "tsconfig"),
    )
    # Standard-library/compiler checks are available for common source types,
    # even when a freshly generated project has no test suite yet.
    has_language_check = any(
        path.suffix.lower() in {".c", ".cc", ".cpp", ".go", ".java", ".js", ".mjs", ".py", ".rs", ".ts", ".tsx"}
        for path in source_files
    )
    has_check = has_tests or has_build or has_language_check

    modified_suffixes = {
        Path(path).suffix.lower() for path in state.modified_files if Path(path).suffix
    }
    static_only = bool(state.modified_files) and modified_suffixes.issubset(_STATIC_SUFFIXES)
    if not state.modified_files:
        static_only = False
    task_text = state.original_task.lower()
    static_task = any(
        phrase in task_text
        for phrase in ("documentation", "document only", "docs only", "文档", "只改注释", "注释")
    ) and not any(
        phrase in task_text
        for phrase in ("code", "website", "site", "app", "项目", "功能", "实现", "编写")
    )

    static_only = static_only and static_task
    if has_tests:
        reason = "test entry point or test framework detected"
    elif has_check:
        reason = "build, syntax, type-check, lint, or smoke validation is available"
    elif static_only and static_task:
        reason = "only static/document files were modified and no executable check was found"
    else:
        reason = "no recognized executable validation was found"
    static_only = static_only and static_task
    return ValidationRequirements(
        has_test_entrypoint=has_tests,
        has_executable_check=has_check,
        static_only=static_only,
        static_task=static_task,
        reason=reason,
    )


@dataclass
class FinishPolicy:
    """FinishAction 的接受策略。"""

    skip_mutation_check: bool = False

    def check(self, state: AgentState, action: FinishAction) -> tuple[bool, str | None]:
        """检查当前 AgentState 是否满足 finish 前提。"""
        if state.task_mode == "greenfield" and state.last_mutation_step == 0:
            return False, (
                "Greenfield task but no files were created yet. Use apply_patch to "
                "create the files first, then call finish."
            )
        if not self.skip_mutation_check and state.last_mutation_step == 0:
            return False, (
                "No files were modified. If the task requires code changes, use "
                "apply_patch to make them first. If no changes are needed, explain why "
                "in the summary and call finish again."
            )

        requirements = validation_requirements(state)
        skip_reason = getattr(action, "validation_skipped_reason", "").strip()

        # Static/document-only work may explicitly document why no command ran.
        # Merely saying "there are no tests" is intentionally not enough.
        if requirements.static_only and skip_reason:
            state.finish_validation_skipped_reason = skip_reason
            return True, None
        if requirements.static_only and not skip_reason and state.last_validation_step == 0:
            return False, (
                "Only static/document files were modified and no executable validation "
                "was found. Provide a non-empty validation_skipped_reason explaining "
                "why validation was skipped, or run an applicable check."
            )

        if state.last_validation_step == 0:
            if not requirements.requires_execution:
                return False, (
                    "No executable validation was found for this generated project. "
                    "Do not finish based only on 'no tests'. Run a syntax, build, lint, "
                    "type-check, or smoke command, or make the work explicitly static "
                    "and provide validation_skipped_reason."
                )
            return False, (
                "You modified files but never ran an available validation. Use "
                "run_command to execute the project's tests, build, syntax check, "
                "type-check, lint, or smoke check before calling finish."
            )

        if state.last_mutation_step > state.last_validation_step:
            return False, (
                f"You modified files after the last validation (mutation at step "
                f"{state.last_mutation_step}, last validation at step "
                f"{state.last_validation_step}). Re-run validation before finishing."
            )

        if state.last_validation_passed is False:
            return False, (
                f"Last validation FAILED. Command: `{state.last_validation_command}`. "
                f"Summary: {state.last_validation_summary or '(no summary)'}. "
                "Fix the failures and re-run validation."
            )

        if state.last_validation_passed is None:
            return False, "Last validation has unknown pass/fail state. Re-run validation."

        return True, None
