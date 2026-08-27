# D-4 健壮性阶段（后天）

**目标**：A–D 四个自建任务全部跑通，无死循环、无 token 爆炸、所有 run 都可审计。

---

## 必做清单

### Context Management（4 小时）

- [ ] `context/working_state.py`
  - `WorkingState` dataclass: `current_goal / important_files / modified / latest_validation / open_questions`
  - **不存模型 CoT**，只存可验证的事实
- [ ] `context/manager.py`
  - `ContextManager.build(state) -> List[Message]`
  - 五段式：System / Original Task / Task Brief / Working State / Recent Interaction
  - Token 估算（tiktoken）
  - 优先级淘汰 P3 → P2 → P1
  - Original Task 永远保留（P0）

### Termination（2 小时）

- [ ] `agent/termination.py`
  - 6 个阈值 + 1 个 stagnation detector：
    - `max_steps=50`
    - `max_model_calls=80`
    - `max_wall_time=1800s`
    - `max_consecutive_errors=5`
    - `max_consecutive_timeouts=3`
    - `repeated_action_limit=3`
    - `stagnation_limit=5`（连续 N 步 modified_files / inspected_files 不变）
  - `should_stop(state) -> (bool, StopReason)`
  - **不擅自终止**：超过阈值时先返回 feedback 一次，再终止

### Trajectory + Error Handling（3 小时）

- [ ] `trajectory/logger.py`
  - 写 JSONL：`{event_id, step, timestamp, type, model, tool, args, result, duration, tokens, error}`
  - 输出到 `runs/run_<timestamp>/trajectory.jsonl`
- [ ] 错误分类
  - `ModelError`：网络 / 限流 → retry
  - `ParserError`：unknown tool / invalid args → 转化为 Observation
  - `ToolError`：path / permission / exception → 结构化错误
  - `CommandFailure`：exit != 0 → **正常** Observation
  - `ControlError`：阈值超 → Protective Stop

### 单元测试（2 小时）

- [ ] `tests/unit/test_parser.py`：合法/非法 tool call 归一
- [ ] `tests/unit/test_state.py`：state update 正确性
- [ ] `tests/unit/test_termination.py`：6 个阈值触发
- [ ] `tests/unit/test_path_boundary.py`：`../../etc/passwd` 拒绝
- [ ] `tests/unit/test_context_manager.py`：token 估算 + 淘汰策略
- [ ] `tests/unit/test_runtime.py`：timeout / cwd / output 截断

---

## 验证

```bash
# 1. L1 全跑
make eval-all-l1
# A_safe_divide:    resolved
# B_cache_clear:    resolved
# C_config_friendly: resolved (大概率)
# D_chunked_robust:  resolved (如果模型够强)

# 2. 单元测试
make test
# 应有 ~20 个测试

# 3. 健壮性测试：跑一个会失败的输入
make eval TASK=C_config_friendly
# 即使 fail，也应该在 max_steps 内停，不烧光 token

# 4. trajectory 审查
ls runs/run_*/trajectory.jsonl | head -1 | xargs cat | jq '.'
# 应能看到每一步的事件
```

---

## 关键决策记录

今天要做的几个"为什么"要在代码注释里写清楚：

- `Termination.should_stop` 为什么不是简单的 step > 50？
- `ContextManager` 为什么 P0 永远保留？
- `Runtime.execute` 为什么 timeout 默认 60s？
- `Trajectory` 为什么不压缩？
- `CommandFailure` 为什么不算 error？

这些会成为面试材料。

---

## 收尾

- [ ] commit：`feat: context manager, termination, trajectory logger, error taxonomy`
- [ ] 跑 A–D 全部，记录每任务的 steps/tokens/duration 到 `eval/results/summary.csv`
- [ ] 进入 [d3_tui.md](d3_tui.md)