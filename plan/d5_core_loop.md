# D-5 Core Loop 阶段（明天）

**目标**：跑通自建 A 任务（safe_divide），Agent 能在 ≤ 5 步内完成读 → 改 → 测 → finish 全闭环。

---

## 必做清单

### 上午（4 小时）：ModelClient + ResponseParser

- [ ] `model/client.py`
  - 支持 OpenAI 兼容（DeepSeek / GLM / Qwen 都用同 base_url）
  - **流式输出**（yield chunks）
  - 网络异常 + 429 限流做有限重试（指数退避）
  - 返回 `ModelResponse(content, tool_calls, usage, raw)`
- [ ] `model/types.py`
  - `ToolCall`、`ToolResult`、`ModelResponse` 等 dataclass
- [ ] `model/parsers/openai_compatible.py`
  - 把 provider 响应归一为 `ToolAction / FinishAction / InvalidAction`
  - **不依赖 SDK 的内置解析**，自己写
- [ ] `tools/base.py`
  - `Tool` ABC: `name`, `description`, `schema`, `execute(args, runtime) -> ToolResult`
- [ ] `tools/finish.py`
  - `FinishTool`：必填 `summary`、`validation`

### 下午（4 小时）：Runtime + 5 个核心 Tool

- [ ] `runtime/base.py`
  - `Runtime` ABC: `execute(cmd, cwd, env, timeout) -> RuntimeResult`
- [ ] `runtime/local.py`
  - `LocalRuntime`：subprocess.run + timeout + capture_output
  - 路径 resolve 到 workspace_root
  - stdout/stderr 截断（默认 50KB）
- [ ] `tools/filesystem.py`
  - `ListFilesTool(max_depth=3)`
  - `ReadFileTool(path, start_line, end_line)` — 默认 200 行窗口
  - **Workspace boundary 检查**：拒绝 `..` 路径逃逸
- [ ] `tools/search.py`
  - `SearchCodeTool(query, path, max_results=50)` — 调 ripgrep
- [ ] `tools/patch.py`
  - `ApplyPatchTool`：支持 create / modify / delete
  - 原子写（先写 `.tmp` 再 rename）
  - 记录到 `state.modified_files`
- [ ] `tools/shell.py`
  - `RunCommandTool(cmd, cwd, timeout)` — 委托 Runtime
- [ ] `tools/git_ops.py`
  - `GitDiffTool`：返回 workspace 内 git diff
- [ ] `tools/registry.py`
  - 注册所有 Tool，提供 `get_schemas()`

### 晚上（2 小时）：AgentLoop + 端到端

- [ ] `agent/loop.py`
  - 完整 7 步循环（init / build / generate / parse / dispatch / record / update）
  - 集成 ModelClient + ResponseParser + ToolRegistry + Runtime
  - **不做** ContextManager / TerminationController（M1 阶段够用即可）
- [ ] `cli.py`
  - `--task "..."` `--workspace ./path` `--model deepseek-chat` 参数
- [ ] **端到端测试**：
  ```bash
  make eval TASK=A_safe_divide
  # 应输出：Step 1 search_code → Step 2 read_file → Step 3 apply_patch → Step 4 pytest → Step 5 finish
  ```

---

## 验证

```bash
# 1. eval 任务
make eval TASK=A_safe_divide
# 期望：task A resolved, 4-6 steps

# 2. 单元测试
make test
# 期望：parser / schema / boundary 测试全过

# 3. 手动触发
python -m coding_agent \
    --task "修复 safe_divide 除零错误" \
    --workspace eval/tasks/A_safe_divide \
    --model deepseek-chat
```

---

## 关键代码骨架提示

### AgentLoop 主循环（占位）

```python
def run(task: str, workspace: Path, config: AgentConfig) -> AgentRunResult:
    state = AgentState.initialize(task, workspace)
    registry = default_registry()
    runtime = LocalRuntime(workspace)
    
    while not state.should_stop():
        messages = build_messages(state)  # 简化版：system + user
        response = model_client.generate(messages, registry.schemas())
        action = response_parser.parse(response)
        
        if action.is_finish:
            return finalize(state, action)
        
        if action.is_invalid:
            observation = ToolResult(success=False, content=action.error_msg)
        else:
            tool = registry.get(action.tool_name)
            observation = tool.execute(action.arguments, runtime)
        
        trajectory.record(state, action, observation)
        state.update(action, observation)
    
    return terminate(state)
```

### ModelClient（最小可用）

```python
class OpenAICompatibleClient:
    def __init__(self, api_key: str, base_url: str, model: str):
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
    
    def generate(self, messages, tools) -> ModelResponse:
        # 流式收集，最后合并
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            stream=True,
        )
        # 累积 tool_calls 和 content
        ...
```

---

## 收尾

- [ ] 提交 commit：`feat: model client, parser, runtime, 5 core tools, agent loop`
- [ ] 跑一次完整 demo，截图保留
- [ ] 进入 [d4_robustness.md](d4_robustness.md)