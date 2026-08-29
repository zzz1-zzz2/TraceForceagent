# TraceForce Roadmap

This is the **single source of truth** for what's next.
Other docs (including the archived plans under `docs/archive/pre-p1/`)
are reference only.

---

## Status

| State | Value |
| --- | --- |
| Current code | `main` after Product Reset (tagged `v0.1.0-pre-mvp`) |
| Pre-Reset archive | tag `v0.1.0-pre-mvp` (do not move) |
| Target release | `v0.1.0-alpha.1` |
| Time budget | 5–8 effective working days |
| Platforms | Ubuntu 22.04 / 24.04, WSL2 — Python 3.11 / 3.12 |

## Goal sentence

> A user can launch TraceForce from any Ubuntu/WSL2 working directory,
> chat naturally, read and edit code, run validations, fix failures from
> the previous turn, ask "why did the last run fail?", append a new
> requirement, and safely stop a runaway task.

## Priority order (do not reorder)

1. **Repository Truth** — this document, accurate README, accurate
   Makefile, accurate `.env.example`, accurate CLI surface, all `|| true`
   removed, junk files archived. *This PR.*
2. **Config / Preflight** — `rg` becomes optional (warning, not hard
   fail); bounded Python search fallback; preflight warnings deduped at
   TUI mount; no key fragments anywhere in user-visible output.
3. **ModelResponseGuard + CommandPolicy** — already-landed
   `is_protocol_failure`; finish the trajectory redaction; add an
   allow-list `EnvironmentPolicy` and a validation-only
   `CommandPolicy` that rejects `cat ~/.traceforce`, `rm`, `git push`,
   `curl`, and workspace-external paths; surface that LocalRuntime is
   *Trusted Local Mode*, not a sandbox.
4. **Unified Action Protocol** — `AssistantReplyAction` for plain text;
   `AskUserAction` contract (continuation comes later);
   `RunOutcome` enum; delete the text-only `InvalidAction` path;
   delete the `/chat` separate history; mutation-after-no-validation
   reject; read-only synthesis budget (max 6 read tool calls, max 3
   no-progress turns, exactly 1 final synthesis).
5. **AgentSession + Cancel** — session id stable across runs; per-run
   `run_id`; bounded `PreviousRunSnapshot` so the model never has to
   `cat trajectory.jsonl` to answer "why did the last run fail?";
   `/clear`; workspace switch reset; cooperative cancel (`Ctrl+C`
   during a run → `RunCancelled`, second `Ctrl+C` → exit, idle `Ctrl+C`
   → exit).
6. **TUI Visual MVP** — unified input (one composer for chat + tasks),
   Welcome panel with model + runtime + workspace status, status bar
   (`idle / thinking · turn N / tool · pytest / waiting / cancelling /
   cancelled / completed`), Pilot-tested at 60/80/120 cols, no
   horizontal overflow, preamble de-noised.
7. **Package + Alpha Demo** — `traceforce` / `tracef` / `traceF` /
   `coding-agent` console scripts; default workspace `.`; wheel + sdist;
   clean venv install verified; GitHub prerelease tag
   `v0.1.0-alpha.1`; FocusCat greenfield E2E demo video scripted (no
   recording required to ship).

## Explicit non-goals for the MVP

The following are **deferred** until `v0.1.0-alpha.1` ships. Adding any
of them before the alpha is *out of scope*:

- Token streaming (assistant or shell).
- Full process-group cancel (`SIGTERM`/`SIGKILL` of subprocesses).
- Docker / `bubblewrap` / `nsjail` sandbox.
- Arbitrary `run_command` (anything outside the validation allow-list).
- Auto-install of pip/npm/cargo dependencies.
- WorkspaceChangeTracker extension (read-side bounded hashing on every
  read; large binary diffing). The current tracker is enough.
- Git undo / rollback, on-disk resume, compaction.
- In-run steering queue (post-MVP follow-up only).
- Parallel tool calls (provider-side batching).
- Plugin system, multi-agent routing, cloud sync.
- Native Windows or macOS support.
- Real `GitHub Issues` benchmark or any `SWE-bench` integration.

If a card above is requested mid-MVP, push back: the MVP definition is
that every PR makes a *user-perceptible* improvement, and the list
above is what the user can already do once the MVP ships.

## Per-card contract

Each card is a single commit on `main` with:

1. `Scope` — one paragraph.
2. `Critical files` — full path list.
3. `Reused abstractions` — what is *not* changed.
4. `Test list` — focused tests + full `pytest`.
5. `Acceptance` — observable behaviour, including CLI smoke and (if
   relevant) TUI Pilot.
6. `Non-goals` — what is explicitly **not** in this card.
7. `Rollback boundary` — the smallest commit that reverts the card.

## Out of Product Reset scope (post-MVP backlog)

Captured so we don't keep re-deciding it:

- `P2-2C` AskUser / `WAITING_USER` continuation runs.
- `P2-2D` Permission UI + Git safety.
- `P2-3` Visual Foundation beyond MVP (pixel cat polish, brand).
- `P2-4` Model streaming (`MessageStarted` / `MessageDelta` /
  `ToolCallStarted`).
- `P2-5` Shell streaming + cooperative cancel upgrade to process-group
  kill.
- `P2-6` In-run steering queue.
- `P2-7` Persistence / Resume / Compaction.
- Release Candidate (license check, author tag, GitHub release notes,
  macOS/Windows exploration).

## Done = "the user can feel it"

Every PR must answer:

> *What can the user do now that they could not do before?*

If the answer is "the code is cleaner" or "more tests pass", the PR is
not a product milestone. Move it to `docs/archive/` or skip it.

---

## Change log

- **v0.1.0-pre-mvp** — snapshot at `main @ 8cbe2c9` before this reset.
  Preserves the 7-task coding loop with P2-1E.1 / P2-1E.3 / P2-1D landed.
- **Product Reset (this commit)** — archive historical material,
  rewrite README/Makefile/.env.example to facts, single roadmap here.
- **next** — `rg` optional + Python search fallback (priority 2).