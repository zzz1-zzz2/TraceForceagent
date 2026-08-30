# MVP4-R0 Portable Alpha Audit

**Audit card:** MVP4-R0 — baseline, repository inventory, and release boundary
**Audit date:** 2026-08-30
**Repository:** `zzz1-zzz2/TraceForceagent`
**Audited baseline:** `main @ 3cb82b6`
**Active card after R0:** MVP4-R Portable Alpha

## Outcome

R0 is an audit and bookkeeping card. It establishes the evidence and cleanup
queue for Portable Alpha without changing package metadata, adding a new CLI
alias, rewriting the README, creating a release tag, or deleting historical
files. MVP4.4.1 remains the shipped runtime-hardening baseline.

## Verification evidence

| Check | Result |
| --- | --- |
| Local test baseline | `483 passed` |
| Full source type check | `python -m mypy src` — passed with no issues in 58 source files |
| Changed-file lint | Ruff check passed for the MVP4.4.1 changed files |
| Diff hygiene | `git diff --check` — passed |
| Secret scan | `bash scripts/check_secrets.sh` — passed; no tracked credential found |
| GitHub Actions | [CI run 33303055690](https://github.com/zzz1-zzz2/TraceForceagent/actions/runs/33303055690) — `completed / success` on `3cb82b6` |
| CI job | [unit tests job 99234617233](https://github.com/zzz1-zzz2/TraceForceagent/actions/runs/33303055690/job/99234617233) — all steps successful |

The GitHub commit-status endpoint returned no status records (`total_count: 0`);
that is not treated as a CI failure because the Actions run above is the
available workflow evidence. The current CI workflow executes on Ubuntu with
Python 3.11 only; Python 3.12 coverage is a later R5 gate.

## Portable Alpha support boundary

Supported for the first portable alpha:

- Ubuntu 22.04 and Ubuntu 24.04;
- Ubuntu-based WSL2 environments;
- Python 3.11 and Python 3.12;
- Bash, Git, and ripgrep available on the host.

Not supported for this alpha:

- Native Windows execution outside WSL2;
- Native macOS execution;
- Automatic `git init` in a Greenfield workspace;
- `tmux` or `asciinema` as runtime dependencies (they remain optional
  recording tools only).

Credential and network boundary:

- Reality-Gate tests use fake models or script fixtures and make no network or
  model requests.
- Real credentials must come from process environment or an explicitly passed
  external `--env-file`.
- A target workspace `.env` is never auto-loaded.
- Credential bytes must not be printed or placed in user TOML configuration.

## Top-level repository inventory

| Path | Purpose | R0 disposition |
| --- | --- | --- |
| `src/coding_agent/` | Product source: agent loop, model adapters, runtime, tools, session, trajectory, and TUI | Keep; R1 updates packaging around this source layout |
| `tests/` | Credential-free unit and integration regression suite | Keep; extend with alpha smoke coverage in R5 |
| `benchmarks/` | Benchmark harness and hand-built evaluation tasks A–F | Keep for engineering evaluation; not a runtime dependency |
| `docs/` | Current roadmap plus historical archive | Keep; this audit is current documentation |
| `docs/archive/pre-p1/` | Historical architecture, plans, interview material, and video script snapshots | Keep in R0; review for deletion or separate archival storage in R4 |
| `scripts/` | Bootstrap, development setup, secret scan, and trajectory replay helpers | Keep; review bootstrap credential ergonomics in R4 |
| `examples/` | Small introductory example material | Keep; align examples with the new product entrypoint in R4 |
| `.github/` | GitHub Actions CI workflow | Keep; add Python 3.12 and packaging gates in R5/R6 |
| `Makefile` | Developer command aliases for setup, checks, tests, lint, and local runs | Keep; synchronize product-facing aliases in R1/R4 |
| `.env.example` | Explicit external environment template | Keep; update command examples in R4 after the CLI entrypoint lands |
| `pyproject.toml` | Package metadata, dependencies, scripts, build, test, Ruff, and mypy config | Keep; package metadata and scripts are R1 scope |
| `README.md` | Current user-facing guide, currently behind shipped capabilities | Keep unchanged in R0; rewrite as R4 |
| `TraceForceagent/` | Empty nested `.github/workflows/` directory with no tracked files or Git metadata | Cleanup candidate; do not delete automatically in R0 |
| `workspace/` | Ignored local demo/workspace and generated trajectory residue | Ignored and untracked; remove locally during cleanup, never publish |

## Stale, duplicate, and generated material queue

No bulk deletion was performed in R0. The following items are recorded for
R4 cleanup review:

1. `docs/archive/pre-p1/` contains old pre-P1 architecture and plans, source
   `.docx` snapshots, converted `.txt` files, interview notes, and an old
   video script. They are historical rather than release documentation; decide
   whether to retain a minimal archive or remove redundant binary/text pairs.
2. `TraceForceagent/.github/workflows/` is an empty nested directory and has
   no tracked files; determine why it exists, then remove it if confirmed as a
   local residue.
3. The ignored `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`, `.venv/`,
   Python `__pycache__/` directories, and `workspace/` contents are local
   generated material. They are not tracked, but should be removed before a
   clean release rehearsal.
4. `README.md`, `.env.example`, `Makefile`, roadmap Greenfield examples, and
   TUI preflight messages still show `coding-agent` as the primary command.
   Keep compatibility during R1, then make `tracef` the recommended name in
   R4.
5. `README.md` still describes the product as single-shot and “Not Streamy”,
   which conflicts with shipped Session, model streaming, tool streaming, and
   cancellation behavior. Rewrite only in R4.
6. `scripts/bootstrap.sh` currently copies `.env.example` to a repository-root
   `.env`. R4 must revise this so installation does not encourage credentials
   in a target workspace; explicit external `--env-file` remains the contract.
7. `Makefile` targets currently invoke `coding-agent` and require a caller
   supplied `WORKSPACE` for some commands. Synchronize those targets after R1/R2
   settle the portable command and current-directory defaults.
8. `benchmarks/tasks/` is intentionally retained as evaluation material, but
   it is not part of the end-user Quick Start and should not be presented as a
   release dependency.

## Dependency audit

The dependencies declared in `pyproject.toml` were checked against source
imports and usage:

| Dependency | Finding | Follow-up |
| --- | --- | --- |
| `openai` | Used by `model/client.py` | Keep |
| `httpx2` | Used by `model/client.py` | Keep while the SDK integration requires it |
| `typer` | Used by `cli.py` | Keep |
| `rich` | Used by `cli.py` | Keep |
| `pydantic` | Used by configuration models | Keep |
| `pydantic-settings` | Used by configuration settings | Keep |
| `python-dotenv` | Used by explicit provider env-file resolution | Keep |
| `tiktoken` | Used by context token estimation | Keep |
| `textual` | Used by the TUI | Keep |
| `structlog` | No current source usage found in the R0 grep audit | Confirm removal or planned logging integration in R1; do not silently delete in R0 |
| `pyyaml` | No current source usage found in the R0 grep audit | Confirm removal or planned configuration format in R1; do not silently delete in R0 |

## Metadata, lint, and release gaps

`pyproject.toml` still has the placeholder package metadata (`coding-agent`,
version `0.1.0`, and author `Your Name`) and only the legacy
`coding-agent` console script. These are deliberate R1 tasks. The repository
has no root `LICENSE` file; R1 must add the selected license metadata and file
before packaging a public alpha.

Full-source Ruff currently reports a fixed historical baseline of 17 findings
(primarily missing final newlines plus a small number of import/style issues).
The changed MVP4.4.1 files are clean and CI is successful, but release
materials must not claim “Ruff all green.” The Alpha Release Sprint must either
fix all 17 findings or introduce a documented, fixed, non-growing baseline and
CI enforcement for new violations.

## R0 non-goals and handoff

R0 intentionally does not:

- change `pyproject.toml` metadata or console scripts;
- rewrite `README.md`;
- add `tracef` / `traceforce` aliases;
- change workspace defaults;
- delete archive or generated files in bulk;
- create `v0.1.0-alpha.1` or any release tag;
- make a real provider or network request.

Handoff order:

1. **R1 — package and entrypoints:** metadata, license, `tracef` and
   `traceforce` plus legacy `coding-agent`, wheel/sdist validation.
2. **R2 — portable defaults:** current-directory workspace and no-argument
   TUI behavior across commands.
3. **R3 — configure and credentials:** user-level non-secret settings and
   explicit env-file/process-environment semantics.
4. **R4 — user documentation and cleanup:** one installation path, five-minute
   Quick Start, troubleshooting, and the cleanup queue above.
5. **R5 — clean-host gate:** Ubuntu 22.04/24.04, WSL2, Python 3.11/3.12,
   install/CLI/TUI smoke, and credential-free Reality Gate.
6. **R6 — alpha release:** tag, GitHub Release, wheel, sdist, and accurate
   release notes.
