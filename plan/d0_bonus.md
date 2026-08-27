# D-0 加分项（SWE-bench）

**目标**：固定 5–10 个 SWE-bench Verified 实例，跑出量化结果。

**这是 D-0 可选项**，时间紧可以跳过。

---

## 必做清单（如果 D-1 提前完成）

### SWE-bench 环境（2 小时）

- [ ] 安装 Docker
  ```bash
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker $USER
  ```
- [ ] 登录 Docker Hub
- [ ] clone SWE-bench
  ```bash
  git clone https://github.com/SWE-bench/SWE-bench.git
  ```

### 准备实例（2 小时）

- [ ] 选 5-10 个 SWE-bench Verified 实例：
  - 不要选依赖极重的（numpy / pytorch 等）
  - 优先选 Python 库、CLI 工具
  - 推荐：flask / requests / django / black / pytest 类的实例
- [ ] 写 `eval/swebench/run_instances.py`
  - 接收 instance_id list
  - 每个实例：
    1. 准备 base commit
    2. 跑 Agent
    3. 用 SWE-bench evaluator 验证 patch

### 配置 Agent for SWE-bench（1 小时）

- [ ] 准备 SWE-bench 风格的 task 输入：
  ```python
  task_input = f"""
  Issue: {instance['problem_statement']}
  
  Repository: {instance['repo']}
  Base commit: {instance['base_commit']}
  
  请定位问题，修改代码，使以下测试通过：
  {instance['test_patch']}
  """
  ```
- [ ] `benchmark_mode=True`：禁止 `ask_user`
- [ ] 限制 `max_steps=80`，`max_wall_time=1800`

### 跑评测（4 小时）

- [ ] 跑 5 个实例，记录：
  - resolved / unresolved
  - steps
  - model_calls
  - tokens
  - duration
  - stop_reason
- [ ] 失败案例做错误分类（localization / patch / env / context）
- [ ] 写 `eval/swebench/results.csv`

### README 补充（D-1 已交也能加）

- [ ] 在 README.txt 里加一段"标准评测结果"
- [ ] 不要隐瞒失败案例，报告完整 subset

---

## 验证

```bash
# 单实例
python -m eval.swebench.run_instances \
    --instance-ids django__django-11095 \
    --model deepseek-chat

# 批量
python -m eval.swebench.run_instances \
    --instance-set eval/swebench/selected_5.json \
    --model deepseek-chat \
    --output eval/swebench/results.csv
```

---

## 报告模板

```text
SWE-bench Verified Subset (5 instances)
- django__django-11095: ✓ resolved (12 steps, 23k tokens, 142s)
- flask__flask-2255:    ✓ resolved (8 steps, 18k tokens, 95s)
- requests__requests-2317: ✗ unresolved (localization failure)
- black__black-1234:    ✓ resolved (15 steps, 31k tokens, 178s)
- pytest__pytest-5432:  ✗ unresolved (patch failure)
Resolved: 3/5 (60%)
```

---

## 如果不跑

在 README 里诚实写"未来计划"，并在面试中说明：

> 我没有把 SWE-bench Leaderboard 当作项目目标。项目的核心是 Agent Core 的设计质量，benchmark 只是外部验证。

---

## 收尾

- [ ] commit：`eval: swebench subset results`（如果有结果）
- [ ] 把结果摘要写到 README
- [ ] 准备应对"为什么只过 3/5"的问题（见面试准备手册 Q41）