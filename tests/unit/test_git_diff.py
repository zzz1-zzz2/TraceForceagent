"""git_diff 工具单元测试 — P1-2。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from coding_agent.config import AgentConfig
from coding_agent.runtime.local import LocalRuntime


@pytest.fixture
def git_repo(tmp_path):
    """构造一个空 git repo 作为 workspace。"""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"], cwd=tmp_path, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=tmp_path, check=True
    )
    return tmp_path


@pytest.fixture
def runtime(git_repo):
    cfg = AgentConfig(workspace_root=git_repo)
    return LocalRuntime(workspace=git_repo, config=cfg)


class TestGitDiffSections:
    def test_clean_repo_shows_no_changes(self, runtime):
        from coding_agent.tools.git_ops import GitDiffTool
        tool = GitDiffTool()
        result = tool.execute({}, runtime)
        assert result.success
        assert "(none)" in result.content
        # 三段标题都存在
        assert "## Staged changes" in result.content
        assert "## Unstaged changes" in result.content
        assert "## Untracked files" in result.content

    def test_unstaged_modification_appears(self, runtime, git_repo):
        from coding_agent.tools.git_ops import GitDiffTool

        # commit 一个初始文件
        f = git_repo / "a.txt"
        f.write_text("line1\n")
        subprocess.run(["git", "add", "a.txt"], cwd=git_repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=git_repo, check=True)

        # modify 它
        f.write_text("line1\nline2\n")

        tool = GitDiffTool()
        result = tool.execute({}, runtime)
        assert result.success
        assert "## Unstaged changes" in result.content
        assert "+line2" in result.content

    def test_staged_modification_appears(self, runtime, git_repo):
        from coding_agent.tools.git_ops import GitDiffTool

        # 初始 commit
        f = git_repo / "a.txt"
        f.write_text("line1\n")
        subprocess.run(["git", "add", "a.txt"], cwd=git_repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=git_repo, check=True)

        # modify + add (staged, but not committed)
        f.write_text("line1\nline2\n")
        subprocess.run(["git", "add", "a.txt"], cwd=git_repo, check=True)

        tool = GitDiffTool()
        result = tool.execute({}, runtime)
        assert result.success
        assert "## Staged changes" in result.content
        assert "+line2" in result.content
        # unstaged section should be empty
        assert "## Unstaged changes\n(none)" in result.content

    def test_untracked_file_appears(self, runtime, git_repo):
        from coding_agent.tools.git_ops import GitDiffTool

        # initial commit (空)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-q", "-m", "init"],
            cwd=git_repo, check=True,
        )

        # 创建 untracked 文件
        (git_repo / "new.txt").write_text("hello")

        tool = GitDiffTool()
        result = tool.execute({}, runtime)
        assert result.success
        assert "## Untracked files" in result.content
        assert "new.txt" in result.content

    def test_all_three_sections_together(self, runtime, git_repo):
        """同时有 staged / unstaged / untracked。"""
        from coding_agent.tools.git_ops import GitDiffTool

        # 初始 commit 一个文件
        f = git_repo / "tracked.txt"
        f.write_text("v1\n")
        subprocess.run(["git", "add", "tracked.txt"], cwd=git_repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=git_repo, check=True)

        # 1) 修改 tracked.txt 然后 staged (modification → git add)
        f.write_text("v1\nv2\n")
        subprocess.run(["git", "add", "tracked.txt"], cwd=git_repo, check=True)

        # 2) 再修改 unstaged
        f.write_text("v1\nv2\nv3\n")

        # 3) 创建 untracked
        (git_repo / "untracked.txt").write_text("new file")

        tool = GitDiffTool()
        result = tool.execute({}, runtime)
        assert result.success
        body = result.content

        # Staged: +v2
        assert "## Staged changes" in body
        assert "+v2" in body
        # Unstaged: +v3
        assert "## Unstaged changes" in body
        assert "+v3" in body
        # Untracked: untracked.txt
        assert "## Untracked files" in body
        assert "untracked.txt" in body


class TestGitDiffEdgeCases:
    def test_non_git_repo_returns_clear_error(self, tmp_path):
        """不是 git repo → 清晰错误。"""
        from coding_agent.tools.git_ops import GitDiffTool

        cfg = AgentConfig(workspace_root=tmp_path)
        runtime = LocalRuntime(workspace=tmp_path, config=cfg)

        tool = GitDiffTool()
        result = tool.execute({}, runtime)
        # 不应该是 success（因为 workspace 不是 git repo）
        # 但实现选择把所有 section 都 fail 出来仍然 ok
        # —— 我们要求至少 not a git repository 出现
        assert "not a git repository" in result.content.lower() or not result.success

    def test_max_lines_truncates(self, runtime, git_repo):
        """max_lines 控制输出长度。"""
        from coding_agent.tools.git_ops import GitDiffTool

        f = git_repo / "big.txt"
        f.write_text("line1\n")
        subprocess.run(["git", "add", "big.txt"], cwd=git_repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=git_repo, check=True)

        # 制造大量改动
        with f.open("a") as fp:
            for i in range(500):
                fp.write(f"added line {i}\n")
        subprocess.run(["git", "add", "big.txt"], cwd=git_repo, check=True)

        tool = GitDiffTool()
        result = tool.execute({"max_lines": 50}, runtime)
        assert result.success
        # 应当截断
        assert "more lines" in result.content or result.truncated
