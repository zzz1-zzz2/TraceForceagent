"""Working State：Agent 当前的紧凑状态描述。

程序自动维护，不依赖 LLM summary（避免 hallucination）。
"""

from __future__ import annotations

from coding_agent.agent.state import AgentState


class WorkingStateBuilder:
    """把 AgentState 渲染为 Working State 文本。

    V1 简化版：直接序列化字段；不调 LLM 总结。
    """

    def render(self, state: AgentState) -> str:
        """渲染 Working State。"""
        lines = ["## Working State", ""]

        # 当前目标
        if state.current_goal:
            lines.append(f"**Current Goal**: {state.current_goal}")
            lines.append("")

        # 重要文件
        important = state.important_files or state.modified_files or state.inspected_files
        if important:
            files_list = sorted(important)[:10]
            lines.append(f"**Important Files**: {', '.join(files_list)}")
            lines.append("")

        # 修改文件
        if state.modified_files:
            mod_list = sorted(state.modified_files)[:10]
            lines.append(f"**Modified Files**: {', '.join(mod_list)}")
            lines.append("")

        # 最近 Validation
        if state.recent_validation:
            lines.append(f"**Latest Validation**: {state.recent_validation}")
            lines.append("")

        # 当前发现
        if state.current_findings:
            lines.append("**Current Findings**:")
            for f in state.current_findings[-5:]:
                lines.append(f"  - {f}")
            lines.append("")

        # 未解决问题
        if state.open_questions:
            lines.append("**Open Questions**:")
            for q in state.open_questions[:3]:
                lines.append(f"  - {q}")
            lines.append("")

        return "\n".join(lines) if len(lines) > 1 else "(no state yet)"