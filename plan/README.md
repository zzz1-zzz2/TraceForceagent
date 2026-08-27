# 项目总览与开发计划

> 本目录是**这次考核**（6 天）的完整作战图。
> 与 `doc/architecture_v3.md`（架构设计）和 `doc/evaluation_plan_v1.md`（评测方案）配合使用。

---

## 0. 一句话目标

**D-1 结束前，提交物齐全 + Agent 能跑通真实 Issue + 视频能讲清楚设计**。

---

## 1. 关键日期（北京时间）

| 时间 | 事件 |
|------|------|
| **今天 (D-6)** | 环境 + 骨架 + 设计文档入库 |
| D-5 | Core Loop 跑通 hello-world 级任务 |
| D-4 | 健壮性：Context + Termination + Trajectory |
| D-3 | TUI + Plan Tool + 自建任务全跑通 |
| D-2 | 真实 Issue：先 Django make_toast，再 Flask #2255 |
| D-1 | 视频 + README + 提交材料 |
| D-0 | SWE-bench 1-2 题（加分项） |
| **9 月 2 日 24:00** | 截止，不再推 commit |

---

## 2. 里程碑（每个阶段的可验证产物）

| 阶段 | 名称 | 可验证产物 | 验证命令 |
|------|------|------------|----------|
| **M0** | 骨架 | `python -m coding_agent --help` 可用 | `make dev` |
| **M1** | Core Loop | 自建 A 任务 1 步搞定 | `make eval TASK=A_safe_divide` |
| **M2** | 健壮性 | A–D 四任务全跑通，无死循环 | `make eval-all-l1` |
| **M3** | TUI | TUI 中能完整跑 A 任务 | `make tui` |
| **M4** | 真实 Issue | Django make_toast 通过 | 视频录制 |
| **M5** | 提交 | README + 视频 + git 仓库就绪 | 模拟提交流程 |

---

## 3. 子计划索引

| 文件 | 阶段 | 必读 |
|------|------|------|
| [d6_skeleton.md](d6_skeleton.md) | 今晚 | ✅ 必读 |
| [d5_core_loop.md](d5_core_loop.md) | 明天 | ✅ |
| [d4_robustness.md](d4_robustness.md) | 后天 | ✅ |
| [d3_tui.md](d3_tui.md) | D-3 | ✅ |
| [d2_real_issues.md](d2_real_issues.md) | D-2 | ✅ |
| [d1_video_readme.md](d1_video_readme.md) | D-1 | ✅ |
| [d0_bonus.md](d0_bonus.md) | D-0 | 可选 |
| [eval_tasks.md](eval_tasks.md) | 全程 | L1 任务设计 |
| [self_review_checklist.md](self_review_checklist.md) | 完成后 | 收尾 |

---

## 4. 提交物检查表（D-1 必须全部 ✅）

- [ ] **GitHub 公开仓库**
  - 题目发布后新建
  - 完整 commit 历史
  - 不压缩、不改写
  - D-1 后不再推
- [ ] **README.txt**（≤ 1000 字）
  - 仓库地址
  - 如何运行
  - 特色功能
  - 其它说明
- [ ] **视频**（≤ 2 分钟，mp4，≤ 200 MB）
  - 演示真实任务完整闭环
  - 简要讲解设计
  - 可剪辑、可加速
- [ ] **.zip**
  - 文件名 = 你的姓名
  - 内容：README.txt + 视频
  - 提交至 https://table.nju.edu.cn/dtable/forms/283d6c7d-475a-4f41-8baf-d3f45966ef2d/

---

## 5. 风险与应对

| 风险 | 应对 |
|------|------|
| DeepSeek API 限流 | 备选 GLM-4 / Qwen / Kimi（OpenAI 兼容） |
| Docker 不稳（SWE-bench）| D-0 阶段才需要，提前不必装 |
| WSL 性能 | 项目放 WSL 内 `~/projects/`，不放 `/mnt/c/` |
| 6 天时间紧 | D-2 失败就降级：只录 Django make_toast 一个真实 Issue |
| API key 误提交 | `scripts/check_secrets.sh` 提交前必跑 |

---

## 6. 不在本次范围（明确非目标）

- 多 Agent 协作
- 长期向量 Memory / RAG
- IDE 插件 / Web UI / 远程 Agent Server
- 云端代码执行 / 微调
- SWE-bench Leaderboard 排名
- 完成度 100%（能跑通核心闭环即可）

---

## 7. 每日时间分配建议

| 时间段 | 用途 |
|--------|------|
| 上午 09:00–12:00 | 核心开发 |
| 下午 14:00–18:00 | 核心开发 + 自测 |
| 晚上 19:00–22:00 | 文档 / 自检 / 调试 |
| 22:00 之后 | 提交 commit、休息 |

---

## 8. 进度追踪

在每个子计划里维护进度（用 `[ ]` 复选框）。

---

**Let's start with [d6_skeleton.md](d6_skeleton.md).**