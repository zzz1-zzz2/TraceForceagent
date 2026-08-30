# TraceForce

> Recovery-oriented single-agent coding agent, written from scratch.
> Linux-only (Ubuntu / WSL2). Alpha quality. Not a sandbox.

---

## What works today

`v0.1.0-pre-mvp` → current `main` (after Product Reset) provides:

- A **single-shot Coding Loop** driven by `AgentLoop` + `AgentState`.
- One LLM client (OpenAI-compatible) with provider-aware credential resolution and an explicit `--env-file`.
- A bounded tool registry: `read_file`, `write_file`, `apply_patch`, `search_code`, `run_command`, `apply_patch`, `list_files`, `finish`, plus the typed `plan` tool.
- Typed event stream (`EventEmitter`) with `ToolStarted` / `ToolCompleted` / `ValidationCompleted` / `RunFinished` and friends.
- Trajectory persistence to `~/.traceforce/runs/<workspace>/<run_id>/trajectory.jsonl` (per-workspace isolation, never inside the target repo).
- **P2-1E.3 WorkspaceChangeTracker** for real mutation detection (replaces tool-name guessing).
- **P2-1E.1 ModelResponseGuard** that rejects truncated responses, multi-tool calls, malformed JSON, and content-filtered outputs *before* dispatching a tool.
- **P2-1D Provider Profile** + user-level `~/.config/traceforce/config.toml` (non-sensitive allow-list) and a unified preflight that flags missing provider/key/workspace without leaking secrets.
- A Textual TUI with `Tool`, `Notice`, and incrementally rendered assistant output, `post_message()` Pilot-tested, fixed chrome at 60/80/120/160 cols.
- A 7-task benchmark harness (`benchmarks/tasks/A_* … F_*`) and 450+ unit/integration tests, all credential-free.

If any of the above stops being true, file an issue — this section is the source of truth.

---

## What this is not

- **Not a sandbox.** `LocalRuntime` is *Trusted Local Mode*: tools are validated against the workspace boundary but `run_command` can read anything the host user can. Permission UI is a future card.
- **Not a Session.** Every `coding-agent run` is one shot. There is no follow-up, no `previous_run` context, no `/clear`, no `/chat` alias, no AskUser/WAITING_USER. These are MVP cards (see roadmap).
- **Not Streamy.** There is no incremental token streaming, no shell-output streaming, no in-run steering.
- **Not an Autonomous Loop.** A single Run terminates on `finish`, validation gate, or termination guard. No daemon, no background, no resume.
- **Not multi-platform.** Linux only this round (Ubuntu 22.04 / 24.04, WSL2). Python 3.11 and 3.12.

If you need any of those, wait for `v0.1.0-alpha` (or read [docs/roadmap.md](docs/roadmap.md) and help).

---

## Installation

```bash
git clone git@github.com:zzz1-zzz2/TraceForceagent.git
cd TraceForceagent
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

This installs the `coding-agent` console script. The `tracef` / `traceF` aliases ship with `v0.1.0-alpha` (PR-M5).

---

## Configuration (two layers, never trusting `workspace/.env`)

TraceForce refuses to read the *target workspace*'s `.env` automatically. If you want credentials, you must opt in.

**Layer 1 — process environment**

```bash
export DEEPSEEK_API_KEY=sk-…        # only the key matching ACTIVE_PROVIDER is used
export ACTIVE_PROVIDER=deepseek     # deepseek | openai | glm | qwen | kimi
```

**Layer 2 — explicit `--env-file`**

```bash
# Put real keys in a file outside the workspace, then pass it explicitly.
coding-agent --env-file ~/traceforce.env check
coding-agent --env-file ~/traceforce.env tui --workspace ~/work/my-project
```

See [.env.example](.env.example) for the schema and the warning about fake placeholders.

**Layer 3 — user-level non-sensitive TOML** (P2-1D, optional)

```bash
mkdir -p ~/.config/traceforce
cat > ~/.config/traceforce/config.toml <<'EOF'
active_provider = "deepseek"
active_model = "deepseek-chat"
temperature = 0.0
max_steps = 50
EOF
```

TOML only accepts non-sensitive keys (`active_provider`, `active_model`, `temperature`, `max_steps`, `log_level`, …). `api_key`, `*_TOKEN`, `*_SECRET`, `permission_policy`, `sandbox` are silently dropped if present — credentials must come from Layer 1 / Layer 2.

---

## Usage

```bash
# Pre-flight (provider, key, workspace, runtime)
coding-agent check                       # uses process env + TOML
coding-agent --env-file ~/traceforce.env check

# Non-interactive single shot
coding-agent run --task "Add a hello() function and a pytest that covers it." \
    --workspace ~/work/my-project

# Interactive TUI (current best entry point)
coding-agent tui --workspace ~/work/my-project
coding-agent --env-file ~/traceforce.env tui --workspace ~/work/my-project
```

CLI surface today: `run`, `tui`, `check`, `config show`, `config path`.
Help: `coding-agent --help` and `coding-agent <command> --help`.

---

## Repository layout (truth)

```text
TraceForceagent/
├── src/coding_agent/         # all product code
│   ├── agent/                # AgentLoop, AgentState, Termination
│   ├── model/                # ModelClient, OpenAI-compatible parser
│   ├── config/               # provider resolver, user TOML, preflight
│   ├── context/              # ContextManager, WorkingState
│   ├── tools/                # typed tool registry
│   ├── runtime/              # LocalRuntime (Trusted Local Mode)
│   ├── recovery/             # Failure-Aware Context Refresh
│   ├── trajectory/           # JSONL sink to ~/.traceforce/runs/
│   ├── tui/                  # Textual widgets + bridge
│   ├── workspace/            # WorkspaceChangeTracker (E.3)
│   └── cli.py                # Typer entry point
├── tests/                    # pytest, credential-free
├── benchmarks/tasks/         # 7 hand-built coding tasks (A–F)
├── docs/
│   ├── roadmap.md            # single source of truth for what's next
│   └── archive/pre-p1/       # historical plans + interview materials
├── scripts/                  # bootstrap, dev helpers
├── examples/                 # minimal hello-world example
├── .github/                  # CI workflows
├── .env.example              # template (empty placeholders)
├── Makefile                  # canonical entry points
├── pyproject.toml
└── README.md                 # this file
```

Historical design notes, 6-day countdown plans, and the original `.docx` files are kept under [docs/archive/pre-p1/](docs/archive/pre-p1/) and are **not** product code.

---

## Verifying an installation

```bash
# from a clean checkout, with no real keys in env
make check           # → missing-key preflight, exit 1, no SDK request made
make test            # → pytest, credential-free, no network
make lint            # → ruff
```

For the credential-free Greenfield Reality Gate, use a clean checkout and a fresh, non-Git directory. Keep the credential file outside the target workspace; the workspace's own `.env` is ignored deliberately:

```bash
empty_dir=$(mktemp -d)
env_file=$(mktemp)
printf 'OPENAI_API_KEY=gate-placeholder\n' > "$env_file"
coding-agent --version
coding-agent --env-file "$env_file" --provider openai check --workspace "$empty_dir"
coding-agent --env-file "$env_file" --provider openai tui --workspace "$empty_dir"
```

The startup check must show the provider, model, workspace, Git, and optional ripgrep checks without making an SDK request. For a no-network run, use the credential-free test suite (the Greenfield E2E injects a fake model), then confirm that the empty directory has no `.git` or generated `.env` and that its trajectory contains durable lifecycle/tool/validation events but no `model_delta`. In an environment without `tmux`, launch the TUI directly and capture the rendered welcome screen; otherwise use the tmux procedure documented by your terminal tooling.

Record the commit, date, platform, Python version, and test result when running this gate. A real model smoke is separate and requires an actual key in an explicit external `--env-file`:

```bash
coding-agent --env-file ~/traceforce.env run --task-file benchmarks/tasks/A_safe_divide/task.md \
    --workspace benchmarks/tasks/A_safe_divide
```

---

## License

MIT (see LICENSE).