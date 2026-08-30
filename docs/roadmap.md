# TraceForce Roadmap

This is the **single source of truth** for the product roadmap. Archived
materials under `docs/archive/` are historical reference only.

---

## Current status

| State | Value |
| --- | --- |
| Current baseline | `main @ a52fca9` |
| Test baseline | `437 passed` |
| Current milestone | **MVP4 Visual Demo** |
| Active card | MVP4.2 Model Streaming Core |
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

## Upcoming milestones

| Milestone | State | User-visible outcome |
| --- | --- | --- |
| MVP4.1 Visual Foundation | ✅ | A calm, compact, recognizable TraceForce TUI at terminal widths from 60 to 160 columns. |
| MVP4.2 Model Streaming Core | 🚧 | Assistant output can arrive incrementally through a typed streaming event contract. |
| MVP4.3 Streaming TUI | ⬜ | The TUI renders incremental assistant output without breaking transcript or terminal state. |
| MVP4.4 Shell Streaming + Process Cancel | ⬜ | Shell output is visible while running and a process group can be cooperatively terminated. |
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
- **MVP4.2** — model streaming core is the active card; implementation in progress.
