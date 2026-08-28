# P1 端到端验证记录

> 日期：2026-08-28
> 用临时 DeepSeek key（inline env var，**未写入任何文件**）跑的真实 API 测试。
> 完成后用户将立即在 DeepSeek 后台删除 key。

## 1. P1-1 / P1-2 / P1-3 / P1-4 单测结果

`make test` 等价命令：`.venv/bin/python -m pytest tests/`

```
157 passed + 1 pre-existing 失败（test_executable_not_found，与 P1 无关）
```

P1-1 / P1-2 / P1-3 / P1-4 全部绿灯。新增 / 改动的测试：

- `tests/unit/test_create_no_overwrite.py` —— P1-1
- `tests/unit/test_git_diff.py` —— P1-2
- `tests/unit/test_failure_refresh_wired.py` —— P1-3（5 个，含 e2e 验证 refresher 真的接进 loop）
- `tests/unit/test_trajectory_layout.py` —— P1-4（5 个，含 git repo 验证轨迹不污染）
- `tests/unit/test_full_loop_e2e.py` —— 迁移到 result.trajectory_path
- `tests/unit/test_invalid_action_loop.py` —— 迁移到 result.trajectory_path

## 2. 真实 API 端到端测试（4 个自建任务）

### Task 1: slugify（pytest 通过但 finish 失败）→ stop_reason: stagnation / max_steps
- 模型正确创建 `strings.py` + `tests/test_strings.py`
- pytest 第一次失败（python 找不到，因为容器里没 `python`，只有 `python3`）
- 模型切换到 `python3`，3 个 test PASSED
- 但接下来调 `git_diff`（workspace 非 git repo 报 runtime_error）
- 然后 read_file `strings.py` 和 `tests/test_strings.py` 各一次（自我审查）
- max_steps 终止，**没调 finish**

### Task 2: fizzbuzz（重复重试同样错误命令）→ max_consecutive_errors
- pytest exit 1（因为 `python` 不存在）
- 模型反复用同样命令 4 次未变
- 触发 max_consecutive_errors 终止

### Task 3: greet（同样 finish 失败）→ max_steps
- 模型创建 `greet.py` 和 `tests/test_greet.py`
- pytest 通过但 agent 进入 self-review + 重复 run_command
- max_steps 终止

### Task 4: safe_divide bug fix（**唯一真正 finish 成功**）→ stop_reason: finish
- 工作区预置了 math_utils.py（带 bug）和 tests/test_math_utils.py（已写好 3 个测试）
- 模型修改 math_utils.py，4 步完成
- pytest 3/3 pass
- **stop_reason: finish, summary 正确**

## 3. 暴露的真实问题（不在 P1 scope，归 P2 阶段）

### 3.1 模型在测试通过后倾向进入 self-review 模式而不 finish
**复现率**：4 个任务里 3 个最终没调 finish
**根因假设**：
- system prompt 第 73 行已说"Always call finish() when done"，但模型仍然倾向反复 read_file 自检
- 终止顺序是 read → git_diff → 第二个 read → max_steps，没有强信号触发 finish

### 3.2 shell `python` 不存在时反复重试
**复现率**：task 2 全程、task 1/3 各一次
**根因假设**：
- agent 不识别 `python: not found` 是环境级错误（永久），不是 transient
- termination 的 `max_consecutive_errors` 阈值需要更低，或者需要把 exit 127 标记为 `is_runtime_error`（这正是 pre-existing 失败的 `test_executable_not_found` 想要修的）
- 修复 `test_executable_not_found` 后，应该能在 max_consecutive_errors 之前就被识别为 runtime error 而透传更明确的 hint

### 3.3 git_diff 在非 git repo 报错信息太僵硬
**复现**：task 1
**模型反应**：read_file 重新自检，而不是改 `git init` 或者直接 finish
**建议**：在 `git_diff` 的 `is_runtime_error=True` observation 里追加"如果你要 diff 但 workspace 不是 git repo，可以 git init 或者直接调 finish"的 hint

## 4. P1 阶段结论

✅ P1-1 `apply_patch create 不覆盖` —— 验证通过
✅ P1-2 `git_diff 显示 staged/unstaged/untracked` —— 验证通过
✅ P1-3 `FailureAwareRefresher 接入 loop` —— 验证通过（含 e2e trajectory 验证）
✅ P1-4 `Trajectory 写到 ~/.traceforce/runs/` —— 验证通过（含 git status 干净）
✅ P1-5 `端到端真实任务` —— **1/4 任务真 finish**（task 4 safe_divide bug fix）

**P1 范围内 5/5 完成**。暴露的 3 个 robustness 问题属于 P2 / D4（robustness）阶段，在 `plan/d4_robustness.md` 跟进。

## 5. 提交清单

```
b0d2798 fix(tools): apply_patch create refuses to overwrite + break tools↔model cycle
ef60e3c feat(git_diff): show staged + unstaged + untracked in one call
b5ea556 feat(agent): wire FailureAwareRefresher into AgentLoop (P1-3)
968d028 feat(trajectory): write to ~/.traceforce/runs/ instead of workspace/runs/ (P1-4)
```