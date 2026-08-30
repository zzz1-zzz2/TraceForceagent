# TraceForce Roadmap

This is the **single source of truth** for the product roadmap. Archived
materials under `docs/archive/` are historical reference only.

---

## Current status

| State | Value |
| --- | --- |
| Current baseline | `main @ 9f8304a` |
| Test baseline | `483 passed` |
| Current milestone | **MVP4 Visual Demo** |
| Active card | **MVP4.4.1 Runtime Hardening** |
| Target release | `v0.1.0-alpha.1` |
| Platforms | Ubuntu 22.04 / 24.04, WSL2 — Python 3.11 / 3.12 |

## Product goal

> A user can launch TraceForce from any Ubuntu/WSL2 working directory,
> inspect and edit code, run bounded validations, understand the last run,
> safely cancel a runaway task, and continue the conversation in a compact,
> trustworthy terminal interface.

## Shipped milestones

### MVP2 — Session and multi-turn foundation ✅

- App-owned `AgentSession` with per-run `run_id` and an active-run guard.
- Bounded previous-run snapshots and safe multi-turn continuation.
- Unified TUI composer; `/clear` preserves the session identity and workspace
  switching creates a new session.
- Atomic tool call/result pairing and terminal commit-before-event ordering.

### MVP3 — Cooperative Cancellation ✅

- Thread-safe, idempotent `CancellationToken` and `RunCancelled` event.
- Cancellation checks at model, parser, tool, validation, and terminal
  boundaries.
- `AgentWorker.cancel()` and running `Ctrl+C` cancellation without killing a
  model call or subprocess.
- `cancelled` Session terminal state, preserved history, released active-run
  guard, and continuation in a later run.

### MVP4.0 — Cancellation Hardening ✅

- Validation completion is emitted before a post-tool cancellation boundary.
- TUI Pilot coverage proves the first `Ctrl+C` only requests cancellation and
  the later deliberate press exits after the repeat guard window.
- Merged to `main` in PR #7; baseline is `main @ d6baaed` with `432 passed`.

### MVP4.1 — Visual Foundation ✅

- Shipped the TraceForce palette, cyan brand treatment, pixel-cat welcome,
  responsive 60/80/120/160-column chrome, and compact tool surfaces.
- Merged to `main` in PR #8; baseline is `main @ a52fca9` with `437 passed`.

### MVP4.2 — Model Streaming Core ✅

- Provider-neutral `ModelStreamDelta` fragments and a durable `ModelStreamAccumulator`.
- Synchronous model compatibility remains explicit; streaming is enabled only by a
  fully initialized streaming-capable client.
- Durable `ModelCompleted` boundaries keep transient `ModelDelta` events out of
  Trajectory persistence.
- Merged to `main` in the MVP4.2 implementation line.

### MVP4.2.1 — Streaming Boundary Hardening ✅

- Model deltas carry incremental text only; the TUI accumulates drafts locally and
  throttles visible assistant updates to approximately 40 ms.
- Final model events replace the streaming draft without duplicate assistant text.
- Cancellation is kept out of model/run failure classification.
- Long-output, repeated-fragment, cancellation, bounded-Trajectory, and empty
  non-Git Greenfield coverage are in the credential-free suite.
- Greenfield Reality Gate completed: the real CLI check and direct TUI startup
  were exercised in a fresh non-Git directory with no SDK request.

### MVP4.3 — Streaming TUI ✅

- Worker identity gate rejects stale `UiAgentEvent`s before the reducer runs;
  terminal lifecycle events also gate on `worker_id` so a late completion
  cannot re-enable composer input or duplicate the final card.
- Keyed `(run_id, turn)` assistant draft and message state replaces the global
  draft without leaking into other turns; `assistant_messages` order is
  preserved on interleaved updates.
- `ModelCompleted` / `AssistantReplied` flush pending renders once, set the
  final content exactly once, and leave the assistant card in place; foreign
  runs, duplicate sequences, and stale turns are dropped by the reducer.
- Integration coverage exercises the real worker thread, reducer, timer
  flush, terminal ordering, cancellation, and the second-run fresh state
  case without SDK/network calls.

### MVP4.4 — Tool Output Streaming + Process Cancel ✅

- `ToolOutputDelta` and `ToolCancelled` events join the lifecycle contract;
  `is_transient_event()` unifies them with `ModelDelta` so Trajectory and
  Session history remain bounded at durable boundaries.
- Runtime ↔ AgentLoop dependency direction is preserved via
  `RuntimeOutputChunk` and `ToolExecutionContext`; the Runtime never depends
  on AgentEvent / EventEmitter.
- `LocalRuntime` now uses `subprocess.Popen` with a drained background
  reader, a cancellation watcher, `start_new_session=True`, and a
  process-group SIGTERM → SIGKILL escalation. `RuntimeResult.cancelled`
  is the authoritative durable boundary.
- The AgentLoop emits the exact `ToolStarted → ToolOutputDelta × N →
  ToolCancelled → RunCancelled` ordering for cancelled `run_command` tools,
  and timeout now emits `ToolFailed` with `is_timeout=True` rather than
  `ToolCancelled`.
- The TUI reducer and presenter accumulate streamed output in
  `ToolUiState.draft`, clear it on terminal events, and keep the bounded
  preview visible without growing without bound.
- The TUI `on_ui_agent_event` worker-identity gate is extended to
  `ToolOutputDelta`, so a stale worker can never corrupt the active card.
- The credential-free suite gains 18 new MVP4.4-5 acceptance cases:
  chunk ordering, repeated-fragment preservation, high-frequency throttling,
  bounded preview, Trajectory `tool_output_delta` exclusion, durable
  `ToolCompleted` content, timeout and cancellation process-group
  termination, cancellation ordering, session call/result pairing, late
  worker-delta rejection, terminal in-place widget update, narrow-width
  layout stability, and non-shell tool zero-regression.

### MVP4.4.1 — Runtime Hardening ✅

- `LocalRuntime` now bounds its raw tail buffer at append time and keeps a
  monotonic stream offset even after old output is evicted.
- Cancellation watchers stop on a shared process-completion signal; cancel
  and timeout remain distinct through Runtime, ToolResult, events, and TUI.
- Cancelled and timed-out commands preserve bounded partial output, while the
  loop emits `ToolCancelled` only for user cancellation and `ToolFailed` for
  timeout.
- Tool-output widgets render through a 70 ms coalescing timer, and real-time
  tests verify in-flight chunks, watcher teardown, bounded storage, and burst
  rendering without credentials or network calls.

### Greenfield Reality Gate

Before starting MVP4.3, verify the actual CLI/TUI boundary from a clean
checkout in a fresh empty directory:

1. Record the commit, date, Linux platform, and Python version.
2. Create a temporary directory with no files, no `.git`, and no workspace
   `.env`; keep any explicit env file outside it.
3. Run `coding-agent --version` and
   `coding-agent --env-file <external-file> --provider openai check --workspace <empty-dir>`.
   The command must resolve the selected provider, report the workspace as
   usable, and make no model/SDK request.
4. Launch `coding-agent --env-file <external-file> --provider openai tui
   --workspace <empty-dir>` and confirm the welcome screen renders. Use a
   detached `tmux` session when available; direct terminal startup is the
   fallback when `tmux` is unavailable.
5. Run the credential-free Greenfield E2E with its fake model. Confirm that
   `apply_patch` creates a file, `python -m py_compile` is classified as
   validation, `finish` is accepted, the final Trajectory has no
   `model_delta`, and the directory remains non-Git with no generated `.env`.

A real provider smoke is separate from this gate and must use a real key in
an explicit env file. The workspace `.env` is never auto-loaded.

## Upcoming milestones

| Milestone | State | User-visible outcome |
| MVP4.1 Visual Foundation | ✅ | A calm, compact, recognizable TraceForce TUI at terminal widths from 60 to 160 columns. |
| MVP4.2 Model Streaming Core | ✅ | Provider-neutral model streaming reconstructs complete responses behind a durable event boundary. |
| MVP4.2.1 Streaming Boundary Hardening | ✅ | Streaming drafts render safely, cancellation remains truthful, and a fresh empty workspace passes the reality gate. |
| MVP4.3 Streaming TUI | ✅ | The TUI renders incremental assistant output without breaking transcript or terminal state. |
| MVP4.4 Tool Output Streaming | ✅ | Shell output is visible while running and the whole process group can be cooperatively terminated. |
| MVP4.5 Final Visual Polish | ⬜ | Status transitions, tool surfaces, and welcome treatment are visually consistent. |
| MVP4.6 Demo Rehearsal | ⬜ | A repeatable alpha demo script exercises the product's strongest user journey. |

---

## MVP4.1 frozen visual specification

MVP4.1 is intentionally a visual foundation card. It must not grow into a
streaming or process-control card.

### Visual direction

> **Pi-style restrained layout + TraceForce cyan brand + a small pixel cat.**

The interface is a focused terminal workbench, not a game HUD or a dashboard.

- Assistant messages have no enclosing border.
- User messages use a lightly raised surface for hierarchy, not a large card.
- Tool messages use a low-contrast surface; success and error are shown with a
  left rule and an icon rather than a full-width colored status bar.
- The Pixel Cat is prominent only in the welcome state.
- Fixed chrome stays compact and leaves the transcript as the primary surface.
- Cyan is the brand color. Large purple regions and saturated rainbow status
  treatments are not allowed.

### Palette

These tokens are the formal MVP4 palette. Components may use opacity or
weight to create hierarchy, but they must not introduce a second palette.

| Token | Value | Use |
| --- | --- | --- |
| `background` | `#17181D` | Screen and transcript ground |
| `surface` | `#202229` | Welcome, composer, footer, user surface |
| `surface-raised` | `#272A33` | Focused or expanded component surface |
| `border` | `#343844` | Quiet separators and input border |
| `text-primary` | `#E6E7EB` | Main readable content |
| `text-secondary` | `#A6AAB5` | Supporting labels and metadata |
| `text-muted` | `#717684` | Low-priority hints and footer text |
| `brand` | `#5ED7E5` | TraceForce identity, focus, active state |
| `accent` | `#9D8CFF` | Sparse secondary emphasis only |
| `success` | `#86C978` | Successful validation and tools |
| `warning-cancelled` | `#D6B86C` | Cancelling and cancelled states |
| `error` | `#F07B72` | Failed tools, validation, and notices |

### Frozen layouts

The layout is designed around two explicit compositions. Intermediate widths
must degrade between them without horizontal scrolling.

#### 120-column standard recording layout

1. One-line BrandBar with product name and compact workspace context.
2. Welcome panel with Pixel Cat, workspace, model, and mode.
3. Short example-task row.
4. Transcript with unboxed assistant content, subtle user surface, and quiet
   tool surfaces.
5. One-line status bar.
6. Single-row composer.
7. One-line footer with model and keyboard hints.

#### 60-column compact layout

- Hide the standard Pixel Cat; use the mini or ASCII fallback only when it
  fits without wrapping.
- Collapse workspace information to a short basename.
- Reduce examples to one short prompt.
- Footer keeps only model and essential keyboard hints.
- Keep the composer single-row and keep all content inside the viewport.
- Never solve a narrow layout by adding horizontal scrolling.

Pilot acceptance widths for this card are **60, 80, 120, and 160 columns**.

### Frozen Pixel Cat forms

MVP4.1 ships three static forms and no animation:

**Standard welcome form**

```text
 /\_/\\
( o.o )
 > ^ <
```

**Mini narrow form**

```text
=^.^=
```

**ASCII fallback**

```text
 /\_/\\
( -.- )
  > <
```

The standard form is used only in the wide welcome panel. The mini form is the
preferred narrow form; the ASCII fallback is used when terminal font or width
makes the mini form unsuitable.

### Status vocabulary

Use these exact user-facing status families, with no competing synonyms:

- `idle`
- `thinking · turn N`
- `tool · <tool name>`
- `waiting`
- `cancelling`
- `cancelled`
- `completed`
- `error`

### MVP4.1 non-goals

Do not add any of the following to the visual foundation card:

- Model token streaming, assistant cursors, or delta events.
- Pending-tool spinners or timer-driven animation.
- Shell partial output or process-group termination.
- Pixel Cat animation or multiple frames.
- Final tool-card redesign beyond palette and hierarchy alignment.
- Permission UI, persistence/resume, steering, or parallel tool calls.

---

## Card contract

Each card is one focused change with:

1. Scope and critical files.
2. Reused abstractions and explicit non-goals.
3. Focused tests plus the full `pytest` suite.
4. Observable acceptance, including CLI smoke and TUI Pilot where relevant.
5. A rollback boundary no larger than the card's commit.

Every card must answer:

> *What can the user do now that they could not do before?*

If the answer is only "the code is cleaner" or "more tests pass," keep the
change out of the product milestone.

## Post-alpha backlog

These remain deliberately outside the current MVP4 cards:

- AskUser / `WAITING_USER` continuation runs.
- Permission UI and Git safety workflows.
- On-disk persistence, resume, and compaction.
- In-run steering queue.
- Parallel provider-side tool calls.
- Plugin system, multi-agent routing, and cloud sync.
- Docker / `bubblewrap` / `nsjail` sandboxing.
- Native Windows or macOS support.
- Release-candidate licensing and packaging exploration.

---

## Change log

- **Product Reset** — archived historical plans and established this file as
  the single roadmap source.
- **MVP2** — shipped Session ownership, continuation, and TUI lifecycle.
- **MVP3** — shipped cooperative run cancellation.
- **MVP4.0** — shipped cancellation hardening in PR #7; `main @ d6baaed`,
  `432 passed`.
- **MVP4.1** — visual foundation specification frozen and shipped in PR #8;
  `main @ a52fca9`, `437 passed`.
- **MVP4.2** — model streaming core shipped on `main`; durable completion boundaries are established.
- **MVP4.2.1** — streaming boundary hardening and the Greenfield Reality Gate are complete; MVP4.3 is next.
- **TUI configuration forwarding** — global `--env-file` and `--provider` now reach both TUI preflight paths and the worker configuration.
- **MVP4.3** — worker identity gate, keyed assistant draft, terminal flush paths, and the real worker→Textual integration coverage are merged on `main`.
- **MVP4.4** — tool-output streaming, `ToolOutputDelta`/`ToolCancelled` lifecycle, runtime/loop decoupling via `RuntimeOutputChunk` + `ToolExecutionContext`, and process-group SIGTERM→SIGKILL termination are merged on `main`; baseline `main @ 581c64c + MVP4.4`, `473 passed`.
