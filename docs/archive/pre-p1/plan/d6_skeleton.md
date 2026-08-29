# D-6 骨架阶段（今晚完成）

**目标**：能在那台 Ubuntu 机器上跑出 `python -m coding_agent --help`，并把设计文档全部入库。

---

## 必做清单

### 环境（30 分钟）

- [ ] Ubuntu 上验证：Python 3.11+ / ripgrep / git / curl
- [ ] 安装 `uv`：`curl -LsSf https://astral.sh/uv/install.sh | sh`
- [ ] 配置 git：`user.name` / `user.email`
- [ ] 配置 SSH key（如果用 SSH 推 GitHub）

### 项目结构（20 分钟）

- [ ] 在 `~/projects/coding-agent/` 下完整创建目录
- [ ] `git init` + `git remote add origin git@github.com:.../coding-agent.git`
- [ ] 把 `doc/`、`plan/`、`scripts/`、`src/`、`eval/`、`tests/`、`examples/`、`video/` 全部创建

### 第一次 commit（10 分钟）

- [ ] `.gitignore` 排除 `runs/`、`.env`、`__pycache__/`、`.venv/`
- [ ] `doc/` 三个 md 文件入库
- [ ] `plan/README.md` 入库
- [ ] commit message：`docs: project skeleton with architecture, eval plan, dev plan`

### Hello world（30 分钟）

- [ ] 写 `src/coding_agent/__init__.py`
- [ ] 写 `src/coding_agent/__main__.py`（接受 `--help`、输出 banner）
- [ ] 写 `src/coding_agent/config.py`（Pydantic Settings）
- [ ] 写 `src/coding_agent/agent/state.py`（AgentState 类定义，可空）
- [ ] 写 `src/coding_agent/agent/loop.py`（loop 函数骨架，return NotImplementedError）
- [ ] 写 `src/coding_agent/cli.py`（Typer CLI，调用 main）
- [ ] `uv venv && uv pip install -e .`
- [ ] `python -m coding_agent --help` 能输出

### 验证（10 分钟）

- [ ] `make dev` 跑通
- [ ] `git log` 能看到 commit
- [ ] `git remote -v` 配好了 origin

### 第二次 commit（5 分钟）

- [ ] commit message：`feat: skeleton with CLI entry, AgentState stub, no-op AgentLoop`

---

## 验证命令

```bash
cd ~/projects/coding-agent

# 1. 项目结构完整
ls -la
# 应看到 README.md, pyproject.toml, src/, tests/, doc/, plan/, scripts/, eval/

# 2. CLI 可用
uv run python -m coding_agent --help
# 应显示帮助文本

# 3. 单元测试通过（即使只有 1 个）
uv run pytest tests/ -v

# 4. git 状态干净
git status
# nothing to commit

# 5. git 历史有 2 次 commit
git log --oneline
# docs: project skeleton with architecture...
# feat: skeleton with CLI entry...
```

---

## 产出文件清单（今晚必须写完）

| 文件 | 类型 | 关键内容 |
|------|------|----------|
| `README.md` | doc | 项目一句话定位 + 5 行运行命令 |
| `pyproject.toml` | config | 依赖：openai、typer、pydantic、pydantic-settings、tiktoken、structlog、textual（后续） |
| `Makefile` | script | `dev` / `test` / `eval` / `tui` / `clean` |
| `.gitignore` | config | 标准 Python + `.env` + `runs/` + `__pycache__/` |
| `.env.example` | config | `DEEPSEEK_API_KEY=`、`MODEL_NAME=`、`API_BASE=` |
| `scripts/bootstrap.sh` | script | `apt install` + `uv install` + `git config` |
| `scripts/check_secrets.sh` | script | 提交前 key 扫描 |
| `src/coding_agent/__init__.py` | code | `__version__ = "0.1.0"` |
| `src/coding_agent/__main__.py` | code | `from .cli import app; app()` |
| `src/coding_agent/cli.py` | code | Typer app: `--task`, `--workspace`, `--model` |
| `src/coding_agent/config.py` | code | `AgentConfig` Pydantic Settings |
| `src/coding_agent/agent/state.py` | code | `AgentState` dataclass（字段全空） |
| `src/coding_agent/agent/loop.py` | code | `run(task, workspace)` 函数骨架 |
| `tests/test_smoke.py` | test | 1 个测试：CLI --help 返回 0 |

---

## 收尾

完成后，把进度勾完，转入 [d5_core_loop.md](d5_core_loop.md)。

**今晚目标：在 Ubuntu 上 22:00 前 push 第一次 commit。**