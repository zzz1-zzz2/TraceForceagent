"""CLI entry point (Typer).

Commands:

* ``python -m coding_agent run --task "..." --workspace ./repo``
* ``python -m coding_agent run --task-file task.md --workspace ./repo``
* ``python -m coding_agent tui [--workspace DIR]``
* ``python -m coding_agent check``
* ``python -m coding_agent config-show``
* ``python -m coding_agent config-path``
* ``python -m coding_agent --help``

Global flags:

* ``--env-file <path>``: explicitly load this env file for credentials and
  base URL. The workspace's own ``.env`` is **never** auto-loaded.
* ``--provider <id>``: select a known provider. Forces credential lookup
  through that provider's env vars only (no cross-provider fallback unless
  ``TRACEFORCE_API_KEY`` is set).

Run-level flags:

* ``--base-url <url>``: override the resolved base URL.
* ``--model <name>``: override the resolved model name.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console

from coding_agent import __version__
from coding_agent.config import (
    PROVIDER_IDS,
    AgentConfig,
    load_config,
    run_preflight,
)
from coding_agent.model.client import MissingCredentialsError

app = typer.Typer(
    name="coding-agent",
    help="Lightweight single-agent coding agent",
    no_args_is_help=True,
    add_completion=False,
)

console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"coding-agent [bold cyan]{__version__}[/bold cyan]")
        raise typer.Exit()


def _env_file_callback(value: Path | None) -> Path | None:
    if value is None:
        return None
    if not value.exists():
        console.print(f"[red]--env-file not found:[/red] {value}")
        raise typer.Exit(2)
    return value


def _provider_callback(value: str | None) -> str | None:
    if value is None:
        return None
    if value not in PROVIDER_IDS:
        console.print(
            f"[red]Unknown provider {value!r}.[/red] "
            f"Available: {', '.join(PROVIDER_IDS)}"
        )
        raise typer.Exit(2)
    return value


@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show version",
    ),
    env_file: Path | None = typer.Option(
        None,
        "--env-file",
        callback=_env_file_callback,
        help="Explicit env file to load (e.g. ~/traceforce.env). The workspace's "
        "own .env is never auto-loaded.",
    ),
    provider: str | None = typer.Option(
        None,
        "--provider",
        callback=_provider_callback,
        help="Active provider id. Determines which env var carries the API key.",
    ),
) -> None:
    """TraceForce coding agent CLI."""
    # Stash shared options in ctx.obj so subcommands can read them. Typer's
    # callback return values for `--env-file` / `--provider` do not survive
    # into ctx.params automatically, so we forward them explicitly.
    ctx.ensure_object(dict)
    ctx.obj["env_file"] = env_file
    ctx.obj["provider"] = provider


def _resolve_config(env_file: Path | None, provider: str | None) -> AgentConfig:
    """Shared configuration loader used by every command."""
    return load_config(env_file=env_file, provider=provider)


def _print_credentials_status(config: AgentConfig) -> None:
    """Render the current provider/key/source without leaking the key itself."""
    if config.api_key:
        masked = f"{config.api_key[:6]}…{config.api_key[-2:]}" if len(config.api_key) > 8 else "***"
        console.print(
            f"[green]✓[/green] provider={config.active_provider} "
            f"source={config.credential_source} env={config.credential_env or '?'} "
            f"key={masked}"
        )
        console.print(
            f"  model={config.active_model} base_url={config.active_base_url}"
        )
    else:
        env_var = {
            "deepseek": "DEEPSEEK_API_KEY",
            "openai": "OPENAI_API_KEY",
            "glm": "GLM_API_KEY",
            "qwen": "QWEN_API_KEY",
            "kimi": "KIMI_API_KEY",
        }.get(config.active_provider, "TRACEFORCE_API_KEY")
        console.print(
            f"[red]✗[/red] provider={config.active_provider} no API key resolved. "
            f"Set {env_var} in your shell, or pass --env-file pointing to a file "
            f"containing {env_var}=..."
        )


def _print_preflight(config: AgentConfig, *, workspace: Path | None = None) -> bool:
    """Render the preflight result. Returns True iff every check passed."""
    result = run_preflight(config, workspace=workspace, require_credentials=True)
    for line in result.summary_lines():
        if line.startswith("✗"):
            console.print(f"[red]{line}[/red]")
        elif line.startswith("✓"):
            console.print(f"[green]{line}[/green]")
        else:
            console.print(line)
    return result.ok


@app.command()
def run(
    ctx: typer.Context,
    task: str | None = typer.Option(None, "--task", "-t", help="Task description"),
    task_file: Path | None = typer.Option(
        None, "--task-file", "-f", help="Load task from file"
    ),
    workspace: Path = typer.Option(
        "./workspace", "--workspace", "-w", help="Workspace directory"
    ),
    base_url: str | None = typer.Option(
        None, "--base-url", help="Override the resolved base URL"
    ),
    model: str | None = typer.Option(
        None, "--model", "-m", help="Override the resolved model name"
    ),
    max_steps: int | None = typer.Option(
        None, "--max-steps", help="Override max steps"
    ),
    task_mode: str | None = typer.Option(
        None,
        "--task-mode",
        help="Task mode: existing_repository or greenfield (default: auto)",
    ),
    benchmark: bool = typer.Option(False, "--benchmark", help="Benchmark mode"),
) -> None:
    """Run the Agent on a single coding task."""
    env_file: Path | None = ctx.obj.get("env_file") if ctx.obj else None
    provider: str | None = ctx.obj.get("provider") if ctx.obj else None

    config = _resolve_config(env_file, provider)
    if base_url:
        config.active_base_url = base_url
    if model:
        config.active_model = model
    if max_steps:
        config.max_steps = max_steps
    if benchmark:
        config.benchmark_mode = True

    if task_file:
        task_text = task_file.read_text(encoding="utf-8")
    elif task:
        task_text = task
    else:
        console.print("[red]Must provide --task or --task-file[/red]")
        raise typer.Exit(1)

    workspace.mkdir(parents=True, exist_ok=True)
    config.workspace_root = workspace.resolve()

    if not config.api_key:
        _print_credentials_status(config)
        raise typer.Exit(1)

    from coding_agent.agent.loop import run as agent_run

    try:
        result = agent_run(
            task=task_text,
            workspace=config.workspace_root,
            config=config,
            task_mode=task_mode,
        )
        if result.reply:
            console.print(f"\n[cyan]assistant:[/cyan] {result.reply}")
        else:
            console.print(f"\n[green]✓ done:[/green] {result.summary}")
        console.print(f"[dim]Stop reason: {result.stop_reason}[/dim]")
        console.print(f"[dim]Steps: {result.steps}, Tokens: {result.total_tokens}[/dim]")
    except MissingCredentialsError as exc:
        console.print(f"[red]✗ {exc}[/red]")
        raise typer.Exit(1) from exc
    except KeyboardInterrupt:
        console.print("\n[yellow]User interrupted[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")
        raise typer.Exit(1) from e


@app.command()
def tui(
    ctx: typer.Context,
    workspace: Path | None = typer.Option(
        None,
        "--workspace",
        "-w",
        help="Agent workspace (default: current directory)",
    ),
) -> None:
    """Launch the Textual TUI."""
    from coding_agent.tui.app import CodingAgentApp

    env_file: Path | None = ctx.obj.get("env_file") if ctx.obj else None
    provider: str | None = ctx.obj.get("provider") if ctx.obj else None
    CodingAgentApp(
        workspace=workspace,
        env_file=env_file,
        provider=provider,
    ).run()


@app.command()
def check(
    ctx: typer.Context,
    workspace: Path = typer.Option(
        Path("./workspace"), "--workspace", "-w", help="Workspace directory"
    ),
) -> None:
    """Run the unified preflight (provider/model/url/key, workspace, git, rg)."""
    env_file: Path | None = ctx.obj.get("env_file") if ctx.obj else None
    provider: str | None = ctx.obj.get("provider") if ctx.obj else None

    config = _resolve_config(env_file, provider)
    _print_credentials_status(config)
    ok = _print_preflight(config, workspace=workspace)
    if not ok:
        raise typer.Exit(1)


@app.command()
def config_show(ctx: typer.Context) -> None:
    """Show the resolved configuration (without leaking the API key)."""
    env_file: Path | None = ctx.obj.get("env_file") if ctx.obj else None
    provider: str | None = ctx.obj.get("provider") if ctx.obj else None

    config = _resolve_config(env_file, provider)
    console.print(f"[bold]provider[/bold]      {config.active_provider}")
    console.print(f"[bold]base_url[/bold]     {config.active_base_url}")
    console.print(f"[bold]model[/bold]        {config.active_model}")
    console.print(f"[bold]credential_source[/bold]  {config.credential_source}")
    console.print(f"[bold]credential_env[/bold]     {config.credential_env or '?'}")
    console.print(f"[bold]api_key_present[/bold]    {'yes' if config.api_key else 'no'}")
    console.print(f"[bold]workspace_root[/bold]     {config.workspace_root}")
    console.print(f"[bold]trace_root[/bold]         {config.trace_root}")
    console.print(
        f"[bold]user_config[/bold]       {config.user_config_path} "
        f"({config.user_config_source})"
    )


@app.command(name="config-path")
def config_path(ctx: typer.Context) -> None:
    """Print the resolved user-level config path (no values, just the path)."""
    env_file: Path | None = ctx.obj.get("env_file") if ctx.obj else None
    provider: str | None = ctx.obj.get("provider") if ctx.obj else None

    config = _resolve_config(env_file, provider)
    exists_marker = "exists" if config.user_config_path.exists() else "missing"
    console.print(f"{config.user_config_path} ({exists_marker})")


if __name__ == "__main__":
    app()
