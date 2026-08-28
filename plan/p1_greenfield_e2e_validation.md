# P1 Greenfield E2E 验证报告

> 本报告对应 `eval/tasks/E_todo_cli`：从**空目录**开始，让 Agent 自主构建一个可运行的 Todo CLI 项目。
>
> 验收标准（来自 P1 收尾反馈）：不预先提供任何源码、不手动帮助 Agent、正确创建多文件项目、pytest 全绿、`python -m todo` 能实际执行、`stop_reason=finish`、Trajectory 完整保存。

## 1. 任务定义

`eval/tasks/E_todo_cli/task.md`：

```
从空目录构建一个 Todo CLI：
- 子命令：add <text> / list / done <id> / remove <id>
- 数据持久化到 todos.json
- 提供 pytest 测试
- 可通过 python -m todo 运行
```

Workspace：`/tmp/e_todo/`（创建前为空）。

## 2. 运行结果（Run #1）

| 指标 | 值 |
| --- | --- |
| Run ID | `run_1787904752_78f250` |
| Trajectory | `~/.traceforce/runs/e_todo/run_1787904752_78f250/trajectory.jsonl` (34 events) |
| 步骤数 | 16 |
| Token 总量 | 74,390 (in+out) |
| Stop reason | `finish` ✅ |
| `python -m pytest tests/ -v` | **11 passed in 0.02s** ✅ |
| `python -m todo add/list/done/remove` | 全部命令端到端可用 ✅ |
| Final diff | `eval/runs/E_todo_cli_final.diff` (291 行,5 个文件) |

### 2.1 Agent 实际产物（无人工介入）

```
/tmp/e_todo/
├── todo/
│   ├── __init__.py   (3 行)
│   ├── __main__.py   (8 行,入口)
│   ├── core.py       (77 行,load/save/add/list/mark_done/remove)
│   └── cli.py        (59 行,argparse 接口)
├── tests/
│   └── test_core.py  (93 行,11 个测试用例)
└── todos.json        (运行 add 后自动创建)
```

总计 **240 行** Python 源码 + 11 个 pytest 用例。

### 2.2 测试覆盖

```
tests/test_core.py::test_add_todo                                PASSED
tests/test_core.py::test_add_multiple_todos_assigns_incrementing_ids PASSED
tests/test_core.py::test_list_todos_empty                        PASSED
tests/test_core.py::test_list_todos_returns_saved                PASSED
tests/test_core.py::test_mark_done                               PASSED
tests/test_core.py::test_mark_done_not_found                     PASSED
tests/test_core.py::test_remove_todo                             PASSED
tests/test_core.py::test_remove_todo_not_found                   PASSED
tests/test_core.py::test_load_todos_missing_file                 PASSED
tests/test_core.py::test_load_todos_corrupt_file                 PASSED
tests/test_core.py::test_next_id_after_removal                   PASSED
============================== 11 passed in 0.02s ==============================
```

### 2.3 端到端 CLI 验证（手动执行）

```
$ python3 -m todo add 'first item'
Added todo #1: first item
$ python3 -m todo add 'second item'
Added todo #2: second item
$ python3 -m todo list
[ ] 1: first item
[ ] 2: second item
$ python3 -m todo done 1
Marked todo #1 as done.
$ python3 -m todo list
[x] 1: first item
[ ] 2: second item
$ python3 -m todo remove 2
Removed todo #2: second item
$ python3 -m todo list
[x] 1: first item
```

### 2.4 Trajectory 事件流（34 events）

| 事件类型 | 次数 | 备注 |
| --- | --- | --- |
| `model_call` | 12 | LLM 决策 |
| `tool_call` | 21 | 实际工具调用 |
| `finish` | 1 | 终止事件 |
| **Total** | **34** | |

工具使用分布：`apply_patch`(5)、`list_files`(2)、`read_file`(3)、`run_command`(10)、`update_plan`(1)。

Agent 的 mutation 序列：
1. `todo/__init__.py`
2. `todo/__main__.py`
3. `todo/core.py` (初版)
4. `todo/core.py` (修订)
5. `todo/cli.py`
6. `tests/test_core.py`

## 3. 涉及到的 P1 修复点

| 修复点 | 在本次 E2E 中的体现 |
| --- | --- |
| **P1-1 `apply_patch` create 无覆盖** | 5 个新文件 0 冲突，全部 create 成功 |
| **P1-3 `ready_to_finish` + FailureAwareRefresher** | `pytest 11 passed` 后 Agent 自然 finish，无 self-review 死循环 |
| **P1-4 Trajectory 写 `~/.traceforce/runs/`** | 完整 34 events 落盘，不污染 workspace |
| **P1-5 真 GitHub issue 验证** | （上一轮 Click bug fix 已通过,11 步 finish,221 pytest pass）|
| **P1-6 `recent_validation` pass 后必须更新** | Working State 从 "FAIL" 切到 "11 passed"，与 ready_to_finish hint 一致 |
| **TaskMode.GREENFIELD 启发式 + Chinese keyword** | "构建一个 Todo CLI" → greenfield 模式 |
| **FinishPolicy.greenfield escape hatch** | mutation 后立即允许 finish，不需要 validation |
| **ToolTurn atomicity** | apply_patch + run_command 的 assistant+tool_result 严格成对 |

## 4. 验收结论

✅ **不预先提供任何源码** — workspace 初始为空，仅 `task.md`
✅ **不手动帮助 Agent** — 全程无人干预
✅ **正确创建多文件项目** — 5 个源文件 + JSON 持久化文件
✅ **pytest 全绿** — 11 passed in 0.02s
✅ **`python -m todo` 能实际执行** — 4 个子命令全部工作
✅ **stop_reason=finish** — Agent 主动 finish，不是 max_steps / 错误终止
✅ **Trajectory 完整保存** — 34 events JSONL 落盘

## 5. 后续动作（已规划）

- [ ] P1-7 稳定性抽样：再跑 2 次 E_todo_cli，目标 ≥2/3 成功
- [ ] P1-8 CI：GitHub Actions 工作流，跑 `pytest tests/` 必须保持全绿
- [ ] P1-9 冻结 P1 Core，开始 P2：Event Bus / Streaming / TUI / Steering