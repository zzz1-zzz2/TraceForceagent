# Coding Agent

> 一个从零实现的 Single-Agent Coding Agent。LLM 负责决定下一步做什么，Agent Core 负责让这个决定在一个受控、可追踪、可恢复的软件工程环境中不断执行，直到任务完成。

---

## 一句话定位

支持**已有仓库维护**（Bug Fix / Feature / Refactor）和**从零开发**（CLI / REST API / Library）的轻量级 Coding Agent。无 Agent Framework 依赖，所有核心逻辑（Context、Tool、Parser、Runtime、Termination、Error Handling）自行实现。

---

## 5 行运行

```bash
# 1. 准备环境
uv venv && source .venv/bin/activate
uv pip install -e .

# 2. 配置 API Key
cp .env.example .env && vim .env   # 填入 DEEPSEEK_API_KEY 等

# 3. 跑自建任务
make eval TASK=A_safe_divide

# 4. 启动 TUI
make tui

# 5. 跑某个真实 Issue
python -m coding_agent --task-file path/to/issue.md --workspace ./repo
```

---

## 核心特性

1. **Single-Agent Iterative Reasoning–Action Loop** —— 不预设 Plan-and-Act
2. **显式 AgentState** —— 独立于 messages 的控制状态
3. **Full Trajectory + Active Context 分离** —— 审计与决策分离
4. **Native Tool Calling + 7 个 Typed Tools** —— 结构化、可控
5. **LocalRuntime + 抽象接口** —— 未来可换 DockerRuntime
6. **Failure-Aware Context Refresh** —— 测试失败时整理紧凑 Snapshot
8. **Plan Tool** —— 让 LLM 显式维护多步任务计划
9. **真实 GitHub Issue 验证** —— Django / Flask / Werkzeug
10. **完整评测体系** —— L0 单元测试 → L1 自建任务 → L2 真实 Issue → L3 SWE-bench

---

## 项目结构

```text
coding-agent/
├── doc/           # 设计文档（架构、评测、面试）
├── plan/          # 6 天开发计划（D-6 至 D-0）
├── src/coding_agent/   # 主代码
│   ├── agent/     # AgentLoop、AgentState、Termination
│   ├── model/     # ModelClient、Parser
│   ├── context/   # ContextManager、WorkingState
│   ├── tools/     # 7 个 Typed Tools
│   ├── runtime/   # LocalRuntime
│   ├── trajectory/# JSONL 日志
│   └── recovery/  # Failure-Aware Refresh
├── eval/tasks/    # L1 自建任务 A-E
├── tests/         # 单元 + 集成测试
├── scripts/       # bootstrap.sh 等
├── runs/          # 每次 run 产物（gitignored）
└── video/         # 视频脚本
```

---

## 开发计划（按天）

| 阶段 | 目标 | 详见 |
|---|---|---|
| D-6 | 骨架 + git init | [plan/d6_skeleton.md](plan/d6_skeleton.md) |
| D-5 | Core Loop + 5 tools + finish | [plan/d5_core_loop.md](plan/d5_core_loop.md) |
| D-4 | Context + Termination + Trajectory | [plan/d4_robustness.md](plan/d4_robustness.md) |
| D-3 | Textual TUI + Plan Tool | [plan/d3_tui.md](plan/d3_tui.md) |
| D-2 | Django make_toast + Flask #2255 | [plan/d2_real_issues.md](plan/d2_real_issues.md) |
| D-1 | 视频 + README + 提交 | [plan/d1_video_readme.md](plan/d1_video_readme.md) |
| D-0 | SWE-bench 加分项 | [plan/d0_bonus.md](plan/d0_bonus.md) |

---

## 设计文档

- [doc/architecture_v3.md](doc/architecture_v3.md) —— 整体架构设计书
- [doc/evaluation_plan_v1.md](doc/evaluation_plan_v1.md) —— 评测方案
- [doc/interview_prep_v1.md](doc/interview_prep_v1.md) —— 面试准备精简版
- 完整 69 题：[Coding_Agent_面试准备手册_V1.0.md](Coding_Agent_面试准备手册_V1.0.md)

---

## 环境要求

- Python 3.11+
- ripgrep（`sudo apt install ripgrep`）
- git、curl
- Linux / WSL2 Ubuntu 22.04+

---

## 许可证

MIT