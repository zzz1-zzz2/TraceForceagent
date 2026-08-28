# P1-5 真实开源仓库修复验证

> 日期：2026-08-28
> 用真实 DeepSeek API + 真实开源仓库验证 Agent Core

## 任务

**Click 项目** — GitHub `pallets/click` 仓库,2026-08-13 由 Kevin Deldycke 修复的真实 bug:

> Commit `a2ac5839`: "Open the pager temp file in text mode"
> Issue: `_tempfilepager` 用 `mode="wb"` 打开 NamedTemporaryFile,但写入方实际传文本,
> 在 Python 3.5+ 上对非 ASCII 内容会抛 `TypeError: write() argument must be str, not bytes`。

## 准备工作

1. `git clone --depth 50 https://github.com/pallets/click.git`
2. `git checkout 9c4dfda` — 修复前 commit
3. `pip install -e .` — 装 click 本地版本
4. 写 task.md 描述 issue
5. 跑 Agent

## Agent 行为轨迹

| Step | 动作 |
|---|---|
| 1-2 | list_files + read_file `_termui_impl.py` |
| 3 | search_code 找 `NamedTemporaryFile` |
| 4 | read_file 看 pager 调用链 |
| 5 | search_code 看 echo_via_pager 实现 |
| 6 | read_file 看完整函数 |
| 7 | apply_patch: 改 `mode="wb"` → `mode="w", encoding=encoding`, `BinaryIO` → `TextIO` |
| 8-10 | run pytest 验证 (221 passed, 23 skipped) |
| 11 | finish() |

## 最终修复 diff

```diff
-    f = tempfile.NamedTemporaryFile(mode="wb", delete=False)
+    f = tempfile.NamedTemporaryFile(mode="w", delete=False, encoding=encoding)
     try:
-        yield t.cast(t.BinaryIO, f), encoding, color
+        yield t.cast(t.TextIO, f), encoding, color
```

**与原作者 commit `a2ac5839` 的修改一致**。

## 验证

```
$ python3 -m pytest tests/test_termui.py -q
221 passed, 23 skipped in 0.26s
```

- stop_reason: **finish**
- summary: 描述了 root cause 和修复方案
- 只用了 **11 步 / 100,765 tokens**

## 结论

**TraceForce Agent 现在能完成"读 issue 描述 → 探索真实仓库代码 → 独立想出修复方案 → 跑测试验证 → finish"完整闭环。**

这是 P1 阶段的最终能力证明。P1 全部 5 项达成:

| ID | 内容 | 测试 | 真实 e2e |
|---|---|---|---|
| P1-1 | create 不覆盖 | ✅ 7 tests | — |
| P1-2 | git_diff 完整化 | ✅ 7 tests | — |
| P1-3 | FailureAwareRefresher 接入 | ✅ 5 tests | click 用例触发 |
| P1-4 | Trajectory 路径迁移 | ✅ 5 tests | click 用例验证 workspace 干净 |
| P1-5 | 端到端真实仓库 | ✅ 7 tests | click real issue ✅ |

**168 passed + 0 failed**,可以正式宣布 P1 完成。