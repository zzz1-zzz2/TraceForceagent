# D-1 视频 + README 阶段

**目标**：所有提交材料齐全且可提交。

---

## 必做清单

### 视频（4 小时）

- [ ] 写 `video/script.md`：60-90 秒脚本
  - 0:00–0:10  项目介绍（一句话定位）
  - 0:10–0:25 展示任务输入（Flask #2255 / Django）
  - 0:25–0:50 完整运行（**可加速 4x**）：search → read → patch → test → finish
  - 0:50–1:10 展示最终 diff + pytest 通过
  - 1:10–1:30 展示 trajectory.jsonl 关键片段（讲一个有意思的 step）
  - 1:30–1:50 简短讲 1-2 个设计决策（AgentState / Active Context）
  - 1:50–2:00 结尾

- [ ] 录制工具：
  - macOS: QuickTime / OBS
  - Linux: `ffmpeg -f x11grab -r 30 -s 1920x1080 -i :0 output.mp4`
  - Windows: OBS

- [ ] 编辑工具：
  - DaVinci Resolve（免费）
  - 或 ffmpeg 拼接：`ffmpeg -f concat ...`

- [ ] 压缩到 ≤ 200 MB：
  ```bash
  ffmpeg -i raw.mp4 -c:v libx264 -crf 28 -preset slow -c:a aac final.mp4
  ```

### README.txt（2 小时，≤ 1000 字）

```text
Coding Agent — 编程智能体
姓名：[你的姓名]
GitHub: https://github.com/[user]/coding-agent

=== 如何运行 ===
1. 准备环境
   Ubuntu 22.04+ / Python 3.11+
   ripgrep, git, curl

2. 安装依赖
   uv venv && uv pip install -e .

3. 配置 API Key
   cp .env.example .env
   # 编辑 .env 填入 DEEPSEEK_API_KEY

4. 跑自建任务
   make eval TASK=A_safe_divide

5. 跑 TUI
   make tui

=== 特色功能 ===
1. Single-Agent Iterative Reasoning–Action Loop
2. 显式 AgentState（独立于 messages 的控制状态）
3. Full Trajectory + Active Context 分离
4. Native Tool Calling + 7 个 Typed Tools
5. LocalRuntime + 抽象接口（未来可换 DockerRuntime）
6. Failure-Aware Context Refresh（测试失败时整理紧凑 Snapshot）
7. Textual TUI（ClaudeCode 风格终端 UI）
8. Plan Tool（让 LLM 显式维护多步任务计划）
9. 真实 GitHub Issue 验证（Django make_toast / Flask #2255）
10. 完整评测体系（L0-L3 四层）

=== 设计要点（视频里会讲）===
- 为什么不用 Plan-and-Act：因为初始信息不足
- 为什么分 Trajectory 和 Context：审计与决策分离
- 为什么 Typed Tools + Shell：可控 + 通用
- 为什么显式 AgentState：控制判断不应依赖 messages

=== 致谢 ===
参考 mini-SWE-agent, SWE-agent, OpenHands, Agentless 的设计思想
```

### git 历史整理（1 小时）

- [ ] 检查 `git log --oneline`，确认 commit 信息清晰
- [ ] 不要 squash 或 rebase
- [ ] 不要 force push
- [ ] 最后一次 push 在 D-1 22:00 之前

### .env 检查（5 分钟）

- [ ] `bash scripts/check_secrets.sh`
- [ ] 确认 `.env` 不在 git 里
- [ ] 确认没有 `sk-xxx` 出现在任何 tracked 文件

### 提交（30 分钟）

- [ ] 把 README.txt 和视频打包成 `[你的姓名].zip`
- [ ] 上传到 https://table.nju.edu.cn/dtable/forms/283d6c7d-475a-4f41-8baf-d3f45966ef2d/
- [ ] 截图保留

---

## 收尾 checklist

- [ ] GitHub 仓库 URL 写在 README.txt
- [ ] 视频 mp4 ≤ 200 MB
- [ ] README.txt ≤ 1000 字
- [ ] .zip 文件名 = 你的姓名
- [ ] 提交链接填好
- [ ] **D-1 22:00 之后不再 push**