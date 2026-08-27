# 迁移与本地开发指南

> 把项目从 Windows 这台机器迁移到 Ubuntu 开发机，或者在同一台机器上初始化。

---

## 场景 A：Windows 上有设计文档，迁移到 Ubuntu

### 方式 1：GitHub 中转（推荐）

1. **在 Windows 上**：
   ```bash
   cd c:\Users\Administrator\Desktop\codingagent
   git init
   git add .
   git commit -m "init: project skeleton with full design docs and dev plan"
   # 在 GitHub 上创建空 repo（不要勾 README）
   git remote add origin https://github.com/<your-name>/coding-agent.git
   git push -u origin main
   ```

2. **在 Ubuntu 上**：
   ```bash
   cd ~/projects
   git clone https://github.com/<your-name>/coding-agent.git
   cd coding-agent
   bash scripts/bootstrap.sh
   ```

### 方式 2：SCP 直接拷贝

如果你在同一局域网：

```bash
# 从 Windows（PowerShell）
scp -r c:\Users\Administrator\Desktop\codingagent user@ubuntu-host:~/projects/
```

---

## 场景 B：已经在 Ubuntu 上开发，commit 后再同步 Windows

不需要这样做——Windows 只用于查看设计文档，开发都在 Ubuntu 上进行。

---

## 场景 C：纯本地（无 Ubuntu 机器）

如果你决定留在 Windows 开发，可以直接用 WSL2 Ubuntu：

```powershell
# 启动 WSL
wsl -d Ubuntu-22.04

# 在 WSL 里
cd /mnt/c/Users/Administrator/Desktop/codingagent
# ⚠️ 注意：项目放在 /mnt/c/ 下 IO 会慢，最好 mv 到 /home/<user>/
```

---

## 推荐的 GitHub 仓库结构

### 公开仓库（提交考核）

```text
coding-agent/    # 这个仓库（题目要的）
├── README.md
├── pyproject.toml
├── Makefile
├── src/
├── tests/
├── eval/
├── doc/                   # 设计文档（公开）
├── plan/                  # 开发计划（公开）
├── scripts/               # 脚本（公开，但 check_secrets.sh 检查）
├── Coding_Agent_面试准备手册_V1.0.md  # 公开（评审参考）
└── video/                 # 视频脚本（公开）
```

### 私有仓库（设计沉淀，可选）

如果你想把开发日志、个人反思分离：

```text
coding-agent-notes/    # 私有
├── meeting-notes.md
├── debug-journal.md
└── trajectory-runs/
```

题目不要求这个，跳过也行。

---

## 提交前的强制检查

### 1. API key 扫描

```bash
bash scripts/check_secrets.sh
# 应输出：✅ 检查通过，无敏感信息泄漏
```

### 2. 文件清理

```bash
# 删除根目录原始 .docx（已在 .gitignore）
# 保留 .txt / .docx.txt 提取版本

# 视频文件不进仓库
ls video/
# raw/ 和 final/ 应在 .gitignore

# 大文件检查
du -sh runs/* 2>/dev/null | sort -hr | head -5
# 如果某个 run 太大（>50MB），检查是否有 trajectory 错误地保存了大输出
```

### 3. README 和提交材料

- [ ] 仓库根 README.md
- [ ] 单独 README.txt（≤ 1000 字，提交用）
- [ ] 视频文件（mp4 ≤ 200MB，提交用）
- [ ] 打包成 `[姓名].zip`

---

## 日常 commit 节奏建议

```bash
# 功能完成时
git add .
git commit -m "feat: apply_patch tool with atomic write"

# 修复 bug
git commit -m "fix: path boundary check rejects symlink escape"

# 重构
git commit -m "refactor: split TrajectoryLogger into Recorder + Writer"

# 文档
git commit -m "docs: explain Failure-Aware Context Refresh"
```

### Commit message 模板

- `feat:` 新功能
- `fix:` Bug 修复
- `refactor:` 重构（不改变行为）
- `docs:` 文档
- `test:` 测试
- `chore:` 杂项（配置、构建）

---

## 第一次 commit 的时间点

题目说"评委会结合提交时间与内容了解你的开发过程"。建议 commit 时间线：

| 时间点 | 内容 | commit message |
|---|---|---|
| **D-6 当晚** | 骨架 + 设计文档 | `init: project skeleton with architecture v3` |
| D-5 中午 | ModelClient + Parser | `feat: openai-compatible model client and response parser` |
| D-5 晚上 | 5 个 tool + Runtime | `feat: filesystem, search, patch, shell, git tools + local runtime` |
| D-5 深夜 | AgentLoop 跑通 A 任务 | `feat: agent loop + first end-to-end task pass` |
| D-4 中午 | Context + Termination | `feat: context manager and termination controller` |
| D-4 晚上 | Trajectory + 错误分类 | `feat: trajectory logger and error taxonomy` |
| D-3 | TUI + Plan tool | `feat: textual TUI with streaming and plan visualization` |
| D-2 | 真实 Issue | `feat: real issue support (django make_toast, flask 2255)` |
| D-2 | Failure Refresh | `feat: failure-aware context refresh` |
| D-1 | 文档 | `docs: README and submission materials` |
| **D-1 22:00 之后** | **不再 push** | — |

---

## 常见迁移问题

### Q: 我已经在 Windows 上 commit 了，怎么 push 到 GitHub？

```bash
# 设置 GitHub credentials（首次）
git config --global user.name "Your Name"
git config --global user.email "your@email.com"

# 创建 GitHub repo（网页操作：New repository，不要勾 README）
# 然后：
git remote add origin https://github.com/<your-name>/coding-agent.git
git push -u origin main
```

### Q: 远程 Ubuntu 上 git clone 下来后，缺 .env 文件？

```bash
# .env 不在 git 里，需要手动创建
cp .env.example .env
vim .env  # 填入 API key
```

### Q: Ubuntu 上 git push 失败（权限）？

```bash
# 用 SSH 而不是 HTTPS
ssh-keygen -t ed25519
cat ~/.ssh/id_ed25519.pub
# 复制到 GitHub Settings > SSH keys

# 然后改 remote
git remote set-url origin git@github.com:<your-name>/coding-agent.git
git push -u origin main
```

### Q: WSL 里访问 GitHub 慢？

WSL2 通常没问题。如果慢：

```bash
git config --global http.lowSpeedLimit 1000
git config --global http.lowSpeedTime 30
```

---

## 紧急情况处理

### 情况 1：D-2 才发现 Agent 跑不通真实 Issue

**降级方案**：
- 视频改用 Django make_toast（最容易）
- 或用自建 C 任务（config_friendly）作为视频
- README 里诚实说明 Flask 也尝试了但环境问题

### 情况 2：API key 不小心 commit 了

```bash
# 立即更换 key（在 provider 网站）
# 然后：
git filter-branch --force --index-filter \
    "git rm --cached --ignore-unmatch path/to/file" \
    --prune-empty --tag-name-filter cat -- --all
git push --force
# 同时通知评委会：曾误提交，已作废更换
```

### 情况 3：提交后发现视频有错误

视频不在仓库里，只需要重新录 + 重新打包 + 重新上传 zip。

---

## 最后的提醒

- ✅ **9 月 2 日 24:00 截止**，不要拖到最后一天
- ✅ 提交后立刻检查 https://table.nju.edu.cn/ 自己的记录
- ✅ 备份所有材料到云盘（防止本地丢失）
- ✅ 至少提前 2 小时提交（避免网络/系统问题）

---

祝顺利！有问题随时回来翻这份文档。