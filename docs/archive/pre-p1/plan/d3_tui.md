# D-3 TUI 阶段

**目标**：用 Textual 写一个 ClaudeCode 风格的 TUI，能完整跑 A 任务。

---

## 必做清单

### Textual 应用骨架（3 小时）

- [ ] `src/coding_agent/tui/app.py`
  - `CodingAgentApp(App)` 三栏布局：
    ```
    ┌────────────────────────────────────────────────────────┐
    │ Header: step · tokens · model · status                 │
    ├──────────────────────────┬─────────────────────────────┤
    │ Main: 流式输出 + 工具调用 │ Right: Plan + Modified Files│
    │                          │                             │
    ├──────────────────────────┴─────────────────────────────┤
    │ Footer: 输入框                                          │
    └────────────────────────────────────────────────────────┘
    ```
- [ ] 接入 streaming ModelClient
- [ ] Plan 工具：在右侧栏显示 `update_plan` tool 的状态

### Plan Tool（1 小时）

- [ ] `tools/plan.py`
  - `UpdatePlanTool(items: [{status, content}])`
  - LLM 主动调用，更新模型自身的工作列表
  - TUI 渲染到右侧栏

### TUI 增强（2 小时）

- [ ] 工具调用可视化：每次 tool call 显示一个卡片（args + 截断 result）
- [ ] 状态栏实时更新：当前 step、token 用量、剩余预算
- [ ] 颜色：成功绿色、失败红色、Observation 灰色
- [ ] 快捷键：`Ctrl+C` 中断、`Ctrl+L` 清屏、`Enter` 提交

### 演示（2 小时）

- [ ] 录一次 A 任务的 TUI 视频（30 秒加速版）
- [ ] 录一次 B 任务的 TUI 视频（Plan Tool 生效）
- [ ] 截图保留

---

## 关键代码

### App 主类

```python
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, RichLog, Static
from textual.containers import Horizontal, Vertical


class CodingAgentApp(App):
    CSS_PATH = "tui.css"
    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+l", "clear_log", "Clear"),
    ]
    
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="left"):
                yield RichLog(id="output", wrap=True, markup=True)
            with Vertical(id="right"):
                yield Static("Plan", id="plan_label")
                yield RichLog(id="plan_log", wrap=True)
        yield Input(placeholder="Enter your task...", id="input")
        yield Footer()
    
    async def on_input_submitted(self, event: Input.Submitted):
        task = event.value.strip()
        if not task:
            return
        event.input.value = ""
        await self.run_agent(task)
```

---

## 验证

```bash
# TUI 启动
make tui
# 输入任务，回车开始

# 自动跑 A 任务（不交互）
make eval-tui TASK=A_safe_divide
# 截图为视频素材
```

---

## 收尾

- [ ] commit：`feat: textual TUI with streaming, plan tool, status bar`
- [ ] TUI 截图 2-3 张存入 `video/screenshots/`
- [ ] 进入 [d2_real_issues.md](d2_real_issues.md)