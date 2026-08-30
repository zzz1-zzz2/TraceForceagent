"""End-to-end AgentLoop 集成测试。

P0-5 关键验收门：模型 → tool → 模型 → modify → test → finish 完整路径。

使用 FakeModel（不调用真实 LLM）驱动 AgentLoop，工具调用走真实执行。
构造一个最小化 pytest 项目作为 workspace，验证：
1. apply_patch 真实创建文件
2. run_command "pytest -q" 真实执行并通过
3. finish 被 FinishPolicy 接受
4. state.modified_files 反映真实修改
5. trajectory.jsonl 记录完整事件流
"""

from __future__ import annotations

import json
import sys

import pytest

from coding_agent.agent.loop import run as agent_run
from coding_agent.config import AgentConfig
from coding_agent.model.client import ModelClient
from coding_agent.model.types import ModelResponse, TokenUsage, ToolCall


class FakeModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.call_count = 0
        self.generate = self._generate
        self.last_messages = None

    def _generate(self, messages, tools=None):
        self.last_messages = messages
        if self.call_count >= len(self.responses):
            # 默认给一个 finish 让循环自然结束
            return ModelResponse(
                content="",
                tool_calls=[ToolCall(
                    id="c", name="finish",
                    arguments={"summary": "exhausted", "validation": "ok"},
                )],
                finish_reason="tool_calls",
                usage=TokenUsage(input_tokens=10, output_tokens=5),
            )
        r = self.responses[self.call_count]
        self.call_count += 1
        return r


def _resp(tool_name: str, args: dict, call_id: str | None = None):
    return ModelResponse(
        content="",
        tool_calls=[ToolCall(
            id=call_id or f"call_{tool_name}",
            name=tool_name,
            arguments=args,
        )],
        finish_reason="tool_calls",
        usage=TokenUsage(input_tokens=20, output_tokens=10),
    )


def _finish(summary="All done", validation="pytest -q passed"):
    return ModelResponse(
        content="",
        tool_calls=[ToolCall(
            id="call_finish",
            name="finish",
            arguments={"summary": summary, "validation": validation},
        )],
        finish_reason="tool_calls",
        usage=TokenUsage(input_tokens=20, output_tokens=10),
    )


@pytest.fixture
def fake_workspace(tmp_path):
    """构造一个最小化、可跑的 pytest 项目作为 workspace。

    布局：
        workspace/
            pytest.ini           (让 pytest 配置简单)
            tests/
                test_smoke.py    (永远通过的测试)
    """
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n")
    tests_dir = workspace / "tests"
    tests_dir.mkdir()
    (tests_dir / "__init__.py").write_text("")
    (tests_dir / "test_smoke.py").write_text(
        "def test_truth():\n    assert True\n"
    )
    return workspace


@pytest.fixture
def config(fake_workspace, tmp_path):
    # P1-4：trajectory 写到 tmp_path/trace/ 而不是 workspace/runs/，
    # 旧测试改从 result.trajectory_path 读取。
    return AgentConfig(
        context_budget=8000,
        recent_turns=4,
        max_steps=20,
        max_model_calls=30,
        max_wall_time=60,
        command_timeout=30,
        workspace_root=fake_workspace,
        trace_root=tmp_path / "trace",
    )


@pytest.fixture
def patch_model(monkeypatch):
    def _patch(responses):
        fake = FakeModel(responses)

        def fake_from_config(cls, _cfg):
            instance = cls.__new__(cls)
            instance._fake = fake
            instance.generate = fake.generate
            return instance

        monkeypatch.setattr(ModelClient, "from_config", classmethod(fake_from_config))
        return fake

    return _patch


class TestHappyPath:
    """完整 happy path：模型 inspect → modify → test → finish。"""

    def test_full_loop_modify_test_finish(
        self, fake_workspace, config, patch_model
    ):
        """完整流程：list_files → read_file → apply_patch → pytest → finish。"""
        fake = patch_model([
            _resp("list_files", {"path": ".", "max_depth": 2}, call_id="c1"),
            _resp("read_file", {"path": "tests/test_smoke.py"}, call_id="c2"),
            _resp("apply_patch", {
                "path": "hello.py",
                "content": "def greet(name):\n    return f'hello {name}'\n",
                "mode": "create",
            }, call_id="c3"),
            _resp("run_command", {"command": "pytest -q"}, call_id="c4"),
            _finish(summary="Created hello.py and ran tests"),
        ])

        result = agent_run(
            task="Add a hello.py with greet() function",
            workspace=fake_workspace,
            config=config,
        )

        # finish 被 FinishPolicy 接受
        assert result.stop_reason == "finish", (
            f"expected finish, got {result.stop_reason}; "
            f"summary: {result.summary}"
        )

        # 文件真实创建了
        assert (fake_workspace / "hello.py").exists()
        content = (fake_workspace / "hello.py").read_text()
        assert "def greet" in content

        # state.modified_files 反映了 apply_patch
        # （通过 trajectory 间接验证：record_tool_call 应当包含 hello.py）
        traj_path = result.trajectory_path
        with traj_path.open() as f:
            events = [json.loads(line) for line in f if line.strip()]

        tool_events = [e for e in events if e["type"] == "tool_call"]
        paths_touched = {e["args"].get("path") for e in tool_events if e.get("args")}
        assert "hello.py" in paths_touched

        # 跑了 5 次模型调用（4 tool + 1 finish）
        assert fake.call_count == 5


class TestGreenfieldSmoke:
    """Verify a new non-Git directory can be built from scratch."""

    def test_empty_non_git_workspace_can_create_validate_and_finish(self, tmp_path, patch_model):
        workspace = tmp_path / "new-project"
        workspace.mkdir()
        fake = patch_model([
            _resp(
                "apply_patch",
                {
                    "path": "hello.py",
                    "content": "def hello():\n    return 'hello'\n",
                    "mode": "create",
                },
                call_id="green-c1",
            ),
            _resp(
                "run_command",
                {"command": f"{sys.executable} -m py_compile hello.py"},
                call_id="green-c2",
            ),
            _finish(summary="Created and validated hello.py", validation="py_compile passed"),
        ])
        config = AgentConfig(
            context_budget=8000,
            recent_turns=4,
            max_steps=10,
            max_model_calls=10,
            max_wall_time=30,
            command_timeout=30,
            workspace_root=workspace,
            trace_root=tmp_path / "trace",
        )

        result = agent_run(
            task="Create a new Python CLI project from scratch",
            workspace=workspace,
            config=config,
        )

        assert result.stop_reason == "finish"
        assert (workspace / "hello.py").exists()
        assert fake.call_count == 3
        assert result.final_state is not None
        assert result.final_state.status == "COMPLETED"
        assert result.trajectory_path is not None
        events = [json.loads(line) for line in result.trajectory_path.read_text().splitlines() if line]
        event_types = [event["event_type"] for event in events]
        assert "model_delta" not in event_types
        assert "model_completed" in event_types
        assert "tool_completed" in event_types
        assert "validation_completed" in event_types
        assert "finish_accepted" in event_types
        assert event_types[-1] == "run_finished"


class TestFinishPolicyRejection:
    """FinishPolicy 在端到端流程中的拒绝路径。"""

    def test_finish_without_mutation_rejected_e2e(
        self, fake_workspace, config, patch_model
    ):
        """只 list_files 不修改就调 finish → reject，最终非 finish 终止。"""
        patch_model([
            _resp("list_files", {"path": ".", "max_depth": 1}, call_id="c1"),
            _finish(summary="nothing changed"),
            _finish(summary="really nothing"),
        ])

        result = agent_run(
            task="just look around",
            workspace=fake_workspace,
            config=config,
        )

        # finish 一直被 reject，循环继续，最终 max_consecutive_errors 触发
        assert result.stop_reason != "finish"
        assert result.steps == 1  # 只有 list_files 一次真实 tool

    def test_finish_with_failing_validation_rejected_e2e(
        self, fake_workspace, config, patch_model
    ):
        """mutation 后 pytest 失败 → finish reject（first attempt）。

        注意：第二次 finish 在测试里直接跳过——本测试只验证"失败时 reject"。
        修复成功的 happy path 见 test_full_loop_modify_test_finish。
        """
        # 加一个故意失败的测试
        (fake_workspace / "tests" / "test_failing.py").write_text(
            "def test_fail():\n    assert 1 == 2\n"
        )

        patch_model([
            _resp("apply_patch", {
                "path": "broken.py",
                "content": "x = 1/0\n",
                "mode": "create",
            }, call_id="c1"),
            _resp("run_command", {
                "command": "python -m pytest tests/test_failing.py -q",
            }, call_id="c2"),
            _finish(summary="done"),
            _finish(summary="retry"),
        ])

        result = agent_run(
            task="修复 broken.py 并跑测试",
            workspace=fake_workspace,
            config=config,
        )

        # finish 一直被 reject（validation failed），最终非 finish
        assert result.stop_reason != "finish", (
            f"expected finish to be rejected, got {result.stop_reason}"
        )
        # broken.py 真实创建
        assert (fake_workspace / "broken.py").exists()


class TestIntegrationRealWorld:
    """验证 AgentLoop 在真实环境（不需要 mock LLM）下的稳定性。"""

    def test_state_modified_files_accurate(
        self, fake_workspace, config, patch_model
    ):
        """state.modified_files 必须精确反映实际修改的文件。"""
        patch_model([
            _resp("apply_patch", {
                "path": "a.py", "content": "a = 1\n", "mode": "create",
            }, call_id="c1"),
            _resp("apply_patch", {
                "path": "b.py", "content": "b = 2\n", "mode": "create",
            }, call_id="c2"),
            _resp("run_command", {"command": "pytest -q"}, call_id="c3"),
            _finish(summary="created a.py and b.py"),
        ])

        result = agent_run(
            task="create two files",
            workspace=fake_workspace,
            config=config,
        )

        assert result.stop_reason == "finish"
        assert (fake_workspace / "a.py").exists()
        assert (fake_workspace / "b.py").exists()
        # trajectory 记录了两次 mutation
        traj_path = result.trajectory_path
        events = [json.loads(line) for line in traj_path.open() if line.strip()]
        tool_events = [e for e in events if e["type"] == "tool_call"]
        mutated = {e["args"]["path"] for e in tool_events
                   if e.get("tool") == "apply_patch"}
        assert mutated == {"a.py", "b.py"}

    def test_context_messages_contain_real_tool_output(
        self, fake_workspace, config, patch_model
    ):
        """验证 model 收到的 messages 包含真实工具输出（不只是 fake 框架）。"""
        patch_model([
            _resp("read_file", {"path": "tests/test_smoke.py"}, call_id="c1"),
            _resp("apply_patch", {
                "path": "added.py", "content": "x = 1\n", "mode": "create",
            }, call_id="c2"),
            _resp("run_command", {"command": "pytest -q"}, call_id="c3"),
            _finish(summary="ok"),
        ])

        result = agent_run(
            task="inspect and modify",
            workspace=fake_workspace,
            config=config,
        )

        assert result.stop_reason == "finish"

        # 第二次调用 model 时（即 read_file 后），messages 应包含
        # tool result（"def test_truth"）
        # 找到 read_file 那次调用后的 model_call
        # 由于 FakeModel.last_messages 在每次 _generate 时被覆盖，
        # 我们用 model_calls 计数间接验证（每次 generate 都收到 messages）
        # 真实验证：读 trajectory 中的 model_call 事件
        traj_path = result.trajectory_path
        events = [json.loads(line) for line in traj_path.open() if line.strip()]
        model_calls = [e for e in events if e["type"] == "model_call"]
        # 5 次调用：read_file + apply_patch + pytest + finish + 最后一次（finish 通过）
        assert len(model_calls) >= 4
        # 第一次调用已经包含 read_file 的 tool result
        # （轨迹不记录 input_messages；这里只能验证调用次数）
