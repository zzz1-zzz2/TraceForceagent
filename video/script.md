# 视频脚本（草稿）

> 实际录制时根据 run 结果调整。这里给出一个 90 秒结构。

## 0:00–0:10 开场（10s）

> "我的 Coding Agent 是一个从零实现的轻量级 Single-Agent 编程智能体，支持已有仓库维护和从零开发两种模式。"

[屏幕：TUI 启动画面，显示 version 和 status]

## 0:10–0:25 任务输入（15s）

> "现在我让它完成一个真实任务：修复 Flask Issue #2255 —— 生成相对 URL 时不应要求 SERVER_NAME。"

[屏幕：输入框打 task 内容，回车]

```text
Task: Generating relative url with app context should not require SERVER_NAME.
Repository: pallets/flask
Base commit: <fix 前的 commit>
```

## 0:25–0:50 Agent 运行（25s，加速 4x）

> "Agent 会自主：先搜索 url_for 实现，读取相关代码，定位问题，做最小修改，再跑测试。"

[屏幕：TUI 左侧流式输出，右侧 Plan 工具更新]

```text
[Step 1] search_code 'url_for' → 5 matches in flask/app.py, flask/blueprints.py
[Step 2] read_file flask/app.py:1-100
[Step 3] update_plan
  ☑ Locate url_for
  ☑ Understand _external logic
  ▶ Modify URL adapter
  ☐ Add regression test
  ☐ Run tests
[Step 4] read_file flask/blueprints.py:140-180
[Step 5] apply_patch flask/app.py (modify)
[Step 6] apply_patch tests/test_url_for.py (create)
[Step 7] run_command pytest tests/test_url_for.py
```

## 0:50–1:10 测试结果（20s）

> "第一次 pytest 失败了：SERVER_NAME 缺失时报错。Agent 通过 Failure-Aware Refresh 整理出关键信息——"

[屏幕：显示 Failure Snapshot]

```text
❌ FAILED: tests/test_url_for.py::test_relative_url
Error: ValueError: Server name not detected
Modified files: flask/app.py
Latest finding: url_for with _external=False still checks SERVER_NAME
```

> "然后它继续修复——"

```text
[Step 8] read_file flask/app.py:800-830 (around the failed code)
[Step 9] apply_patch flask/app.py (add _external=False bypass)
[Step 10] run_command pytest tests/test_url_for.py
✓ 1 passed
```

## 1:10–1:30 最终验证（20s）

> "现在看一下最终 diff——"

[屏幕：git_diff 输出]

```diff
diff --git a/flask/app.py b/flask/app.py
@@ -812,7 +812,9 @@ class Flask:
     def url_for(self, ...):
-        if self.config['SERVER_NAME']:
-            ...
+        if not external and not self.config['SERVER_NAME']:
+            return ...  # relative URL, no server name needed
+        if self.config['SERVER_NAME']:
+            ...
```

> "跑完整测试集也通过——"

```text
[Step 11] run_command pytest tests/
✓ 247 passed in 12.4s
```

## 1:30–1:50 设计讲解（20s）

> "Agent 的核心是 7 步循环：构造 context、调模型、解析、分发工具、记录、更新状态、判断终止。LLM 只负责决策，所有执行、状态、终止逻辑都由程序负责。"

[屏幕：显示架构图（静态）]

```
State → ContextManager → LLM → ResponseParser
   ↓                              ↓
AgentLoop                  ToolRegistry
   ↓                              ↓
Termination                Runtime
```

## 1:50–2:00 结尾（10s）

> "完整代码、轨迹、和设计文档都在 GitHub 仓库，面试时见。"

[屏幕：GitHub URL 弹出]

---

## 录制技巧

1. **TUI 录制** 用 `script -c "python -m coding_agent tui" output.log` 然后重放
2. **加速** 用 `ffmpeg -i raw.mp4 -vf "setpts=0.25*PTS" -an fast.mp4`
3. **字幕** 用 `ffmpeg -i fast.mp4 -vf "subtitles=script.srt" final.mp4`
4. **总大小控制** 必要时 `ffmpeg -crf 30 -preset slow` 进一步压缩

## Fallback 视频

如果 Flask 跑不通，用 Django make_toast（更简单，几乎一定能成）：

```text
Task: 为 django.shortcuts 增加 make_toast() 函数，补充测试
```

期望轨迹：4-5 步，read 现有 shortcuts.py → 加函数 → 加测试 → pytest → finish。