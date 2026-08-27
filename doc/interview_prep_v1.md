# 面试准备手册（精简索引）

> 完整版本见 [Coding_Agent_面试准备手册_V1.0.md](../Coding_Agent_面试准备手册_V1.0.md)（在仓库根目录）。
>
> 本文件是 doc/ 下的精简版，仅保留面试问题列表与最关键的口径。完整回答请看仓库根目录那份。

---

## 核心句（全程围绕）

> LLM 负责决定下一步做什么，Agent Core 负责让这个决定在一个受控、可追踪、可恢复的软件工程环境中不断执行，直到任务完成。

---

## 三级回答法（所有问题统一组织）

1. **第一层**：我怎么做（具体实现）
2. **第二层**：为什么（问题来源）
3. **第三层**：为什么不用另一个（counterfactual）

---

## 必练 22 题（面试前不查文档脱口而出）

### A. 架构理解（10 题）

1. 你的 Agent 一轮到底发生什么？
2. AgentState 和 messages 有什么本质区别？
3. 为什么不用严格 Plan-and-Act？
4. 为什么 Typed Tools 和 Shell 要同时存在？
5. 为什么 Full Trajectory 与 Active Context 要分离？
6. 测试失败为什么不是 Tool Error？
7. 如何防止无限循环和重复行动？
8. 为什么 Runtime 要抽象，而不是直接 subprocess？
9. 你的 Agent 怎么同时支持 Greenfield 和 Existing Repo？
10. 你的设计与 mini-SWE-agent / SWE-agent / OpenHands 到底有什么差异？

### B. 设计与实现细节（6 题）

11. AgentState 用什么数据结构？为什么？
12. Context Budget 多少？怎么定的？
13. tool_call_id 怎么对应消息？
14. subprocess timeout 后子进程怎么清理？
15. apply_patch 部分成功怎么办？
16. LLM API retry 会不会造成 Tool 重复执行？

### C. 流式与一致性（3 题）

17. 你的 ModelClient 是 streaming 还是一次性？为什么？
18. 中途网络断开怎么办？
19. 同一 turn 的多个 tool_call 串行还是并行？

### D. 反思与边界（3 题）

20. 如果让你从零再做一次，你会改什么？
21. 你的 Agent 不能做什么？
22. SWE-bench 只过 2 个怎么解释？

---

## 面试中要能画的架构图（1 分钟）

```text
User Task
   ↓
Task Brief
   ↓
AgentState
   ↓
ContextManager
   ↓
LLM
   ↓
ResponseParser
   ↓
ToolRegistry
   ↓
Runtime
   ↓
Observation
   ↓
TrajectoryLogger
   ↓
State Update
   └────────→ 下一轮
```

旁边标注：Termination Controller / Context Budget / Failure Refresh

---

## 反向设计推理（删模块分析）— 评委最爱问

| 删掉 | 后果 |
|---|---|
| Parser | Tool protocol 污染 AgentLoop，错误校验分散 |
| Runtime | Tool 与 OS 耦合，无法切换 DockerRuntime |
| AgentState | messages 勉强运行，但控制判断脆弱 |
| ContextManager | 长任务 history 无限增长 |
| Trajectory | 失去可审计性，无法 debug |
| ToolRegistry | AgentLoop 内部堆满 if 分支 |

---

## 不要犯的口径错误

- ❌ "我的 Agent 是个 ChatGPT 增强版"
- ❌ "我创新了一种 Agent 算法"
- ❌ "用 LangChain 应该也行"（题目禁止）
- ❌ "SWE-bench 没跑是因为时间不够"（要诚实说没把它当目标）
- ❌ "代码是 AI 写的"（要主动说"我对每个模块负责"）

---

## 诚实承认风险

- 安全：LocalRuntime 没有 OS-level sandbox
- Prompt Injection：V1 不完全防御
- 任务类型：不能做 GUI、不能保证 100% 测试通过
- 评测：不一定能跑过 5/10 SWE-bench（要诚实报告并分析失败原因）

---

## 准备策略

1. **D-6 至 D-1**：按 [plan/](../plan/) 推进开发
2. **D-1 之后**：从仓库根目录 [Coding_Agent_面试准备手册_V1.0.md](../Coding_Agent_面试准备手册_V1.0.md) 精读全部 69 题
3. **面试前 2 天**：从 69 题里挑出这 22 题精练
4. **面试前 1 天**：找同学 mock interview 30 分钟