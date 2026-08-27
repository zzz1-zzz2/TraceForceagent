# Hello World 演示

这是 Coding Agent 的最小演示用例。

## 启动

```bash
# 方式 1：CLI 直接跑
python -m coding_agent --task "Create a hello.py that prints 'Hello, World!'"

# 方式 2：TUI
python -m coding_agent tui
```

## 期望输出

```
$ python -m coding_agent --task "Create a hello.py..."

Step 1: list_files(.)
  └─ (empty directory)

Step 2: apply_patch(path="hello.py", mode="create", content="print('Hello, World!')")
  └─ Created hello.py

Step 3: run_command(command="python hello.py")
  └─ Hello, World!

Step 4: finish(summary="Created hello.py", validation="ran successfully")
  └─ Task finished.

Steps: 4, Tokens: 1234, Duration: 12.3s
```

## 期望产物

```text
.
├── hello.py
└── runs/run_<timestamp>/
    ├── trajectory.jsonl
    └── final.diff
```

## 验证

```bash
# 跑 hello 任务
make eval TASK=E_todo_cli  # 或者用 hello_world 任务

# 验证 trajectory 可读
python scripts/replay_trajectory.py runs/run_*/trajectory.jsonl
```