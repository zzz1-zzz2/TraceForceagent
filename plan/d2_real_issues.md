# D-2 真实 Issue 阶段

**目标**：跑通 1 个真实开源仓库 Issue 作为视频演示。

---

## 必做清单

### 上午：Django make_toast（3 小时）

- [ ] 准备任务：
  ```bash
  mkdir -p eval/real/django_make_toast
  cd eval/real/django_make_toast
  git clone https://github.com/django/django.git
  cd django
  # 选一个 base commit（修复前的）
  git checkout <base_commit>
  ```
- [ ] 任务描述（写进 `eval/real/django_make_toast/task.md`）：
  > 为 `django.shortcuts` 增加 `make_toast()` 函数，补充测试。
  > 参考 Django 官方贡献教程。
- [ ] 跑：
  ```bash
  python -m coding_agent \
      --task-file eval/real/django_make_toast/task.md \
      --workspace eval/real/django_make_toast/django \
      --model deepseek-chat
  ```
- [ ] 期望：Agent 自动找到 `django/shortcuts.py`，添加函数，在 `tests/shortcuts/` 加测试，跑 pytest

### 下午：Flask #2255（4 小时）

- [ ] 准备任务：
  ```bash
  mkdir -p eval/real/flask_2255
  cd eval/real/flask_2255
  # 找到修复 PR 之前的 commit
  git clone https://github.com/pallets/flask.git
  cd flask
  git checkout <base_commit_before_fix>
  ```
- [ ] 任务描述（基于真实 Issue 文本）：
  > Issue: Generating relative url with app context should not require SERVER_NAME
- [ ] 跑两次：
  - 第一次：观察 Agent 行为路径
  - 第二次：录视频
- [ ] 期望轨迹：search url_for → read 源代码 → 找 _external 逻辑 → 修改或加分支 → 加 regression test → pytest

### 晚上：Failure-Aware Refresh 启用（1 小时）

- [ ] `recovery/failure_refresh.py`
  - 检测 `pytest` exit != 0
  - 用正则抽取：失败 test 名 / assertion / 当前 diff
  - 构造紧凑 Snapshot 替换长 traceback
  - 更新 Working State 的 `current_findings`
- [ ] 开关：`enable_failure_refresh: bool`（默认 True）
- [ ] 重跑 Flask 任务验证 Observation 真的变紧凑

---

## 验证

```bash
# 1. Django make_toast
make eval-real TASK=django_make_toast
# 期望：resolved，patch 含 shortcuts.py + tests/shortcuts/

# 2. Flask #2255
make eval-real TASK=flask_2255
# 期望：resolved，patch 含 src + test

# 3. 检查 diff 质量
cat runs/run_<timestamp>/final.diff
# 应该是干净的最小 patch
```

---

## 视频素材准备

如果两次都成功：
- 视频用 Flask #2255（更真实、更有戏剧性）
- 备份 Django 视频作为 fallback

如果只有 Django 成功：
- 视频用 Django make_toast
- 在 README 里说明 Flask 也尝试了

如果都没成功：
- 视频用自建 C 任务（config_friendly，最像真实任务）
- 在 README 里诚实说明真实 Issue 失败原因

---

## 收尾

- [ ] commit：`feat: real-issue tasks (django, flask), failure-aware refresh`
- [ ] 保存 run 产物：`runs/run_<timestamp>/` 完整保留
- [ ] 进入 [d1_video_readme.md](d1_video_readme.md)