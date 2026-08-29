# 完成后自我审查清单

> 项目基本完成后，逐项过一遍这个清单。每一项都要么"通过"、要么"明确写出来为什么不做"。

---

## 1. 代码层

- [ ] 所有模块都有 docstring（≥ 1 行说明职责）
- [ ] 公共函数有类型注解
- [ ] 没有 print() 残留（用 structlog 或 TUI widget）
- [ ] 没有 TODO / FIXME 残留（除非明确记入 issue）
- [ ] 没有 hardcoded API key
- [ ] 没有 hardcoded 绝对路径
- [ ] 没有调试用的 `import pdb; pdb.set_trace()`
- [ ] pyproject.toml 列全了所有运行时依赖
- [ ] `requirements.txt` / `uv.lock` 已生成（即使 D-1 不上传）

## 2. 测试层

- [ ] `make test` 全部通过
- [ ] 单元测试覆盖：parser / state / termination / context / path boundary / runtime
- [ ] 集成测试：跑通 A 任务完整闭环
- [ ] L1 自建任务 A–D 全部跑出结果（pass 或 fail，记录原因）

## 3. 性能层

- [ ] 一次 eval run 总时间 < 10 分钟（A 任务应 < 1 分钟）
- [ ] trajectory.jsonl 不超过 10 MB（除非任务极复杂）
- [ ] 没有 token 爆炸（>500k tokens/run 视为异常）

## 4. 安全层

- [ ] `bash scripts/check_secrets.sh` 输出干净
- [ ] .gitignore 包含 `.env`、`runs/`、`__pycache__/`、`.venv/`
- [ ] 文件 tool 拒绝 `..` 路径逃逸（有测试）
- [ ] command timeout 默认为 60s
- [ ] output 截断默认为 50KB

## 5. 可复现层

- [ ] trajectory.jsonl 包含 messages（可重放）
- [ ] config.json 包含模型、temperature、budget
- [ ] 每个 run 有 timestamp
- [ ] finish.summary / validation 字段非空

## 6. 文档层

- [ ] README.md 项目定位清晰
- [ ] README.md 5 行内能跑出 hello world
- [ ] doc/architecture_v3.md 描述当前实现（不是设计稿）
- [ ] 关键决策（为什么这样设计）有 inline 注释

## 7. 提交层

- [ ] git log 干净、信息清晰
- [ ] 没有大文件意外入库
- [ ] commit 数量合理（不应只有 3-5 个超大 commit）
- [ ] D-1 22:00 之后不再 push

## 8. 面试层

- [ ] 能不查文档画出架构图
- [ ] 能说出 7 个工具的 schema
- [ ] 能说出 AgentState 的所有字段
- [ ] 能说出 6 个终止条件及默认值
- [ ] 能用一句话解释每个模块存在的原因
- [ ] 准备一个真实 trajectory 做"指着某行讲设计"演示

---

## 9. 容易遗漏的检查项（来自真实踩坑）

- [ ] `eval/results/summary.csv` 是否被 .gitignore 排除（避免每次跑都污染 commit）
- [ ] `runs/` 目录下旧 run 是否需要清理（避免仓库膨胀）
- [ ] `__pycache__/` 是否真的被 .gitignore（`find . -name __pycache__` 检查）
- [ ] docx 原始文件是否需要删除（保留 .txt 即可）
- [ ] 视频文件是否在仓库里（视频不进仓库，只在本地）
- [ ] README.txt 是 .txt 不是 .md（提交要求）

---

## 10. 提交前最后一遍

- [ ] 在新 clone 的目录里跑 `make eval TASK=A_safe_divide` 能成功（验证 README 的指引有效）
- [ ] `git log --oneline | head -20` 检查 commit 信息质量
- [ ] 打包 `[你的姓名].zip`，确认只含 README.txt + 视频
- [ ] 上传后下载一次，确认能解压

---

**完成这个清单后，项目就可以交了。**