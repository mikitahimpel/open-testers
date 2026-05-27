"""open-testers command-line interface."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

from open_testers import schema
from open_testers.credentials import VALID_KINDS, CredentialStore
from open_testers.executor import Runner
from open_testers.llm import get_provider
from open_testers.memory import MemoryStore

console = Console()


def _die(msg: str) -> None:
    """Print an error and exit 2 — used as the uniform error escape hatch."""
    console.print(f"[red]Error:[/red] {msg}")
    sys.exit(2)


def _parse_viewport(spec: str) -> tuple[int, int]:
    try:
        w_str, h_str = spec.lower().split("x", 1)
        return int(w_str), int(h_str)
    except (ValueError, AttributeError) as e:
        raise click.BadParameter(
            f"viewport must look like 1280x720, got {spec!r}"
        ) from e


def _parse_secrets(pairs: tuple[str, ...]) -> dict:
    out: dict[str, str] = {}
    for raw in pairs:
        if "=" not in raw:
            raise click.BadParameter(
                f"--secret must be KEY=VALUE, got {raw!r}"
            )
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key:
            raise click.BadParameter(f"--secret key must be non-empty in {raw!r}")
        out[key] = value
    return out


@click.group()
def main() -> None:
    """open-testers — open-source AI-driven QA testing."""


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


@main.command()
@click.argument(
    "yaml_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--llm",
    "llm_name",
    type=click.Choice(["claude", "openai", "ollama", "stub"]),
    default=None,
    help="LLM provider. Defaults to $OPEN_TESTERS_LLM or 'stub'.",
)
@click.option("--dry-run", is_flag=True, help="Force the stub LLM provider.")
@click.option(
    "--headed/--headless",
    "headed",
    default=False,
    help="Run browser headed or headless (default headless).",
)
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    default=Path("runs"),
    show_default=True,
)
@click.option("--max-actions", type=int, default=25, show_default=True)
@click.option("--viewport", default="1280x720", show_default=True)
@click.option(
    "--memory-file",
    type=click.Path(path_type=Path),
    default=Path("open-testers.memory.json"),
    show_default=True,
)
@click.option("--no-memory", is_flag=True, help="Skip loading the memory file.")
def run(
    yaml_path: Path,
    llm_name: Optional[str],
    dry_run: bool,
    headed: bool,
    output: Path,
    max_actions: int,
    viewport: str,
    memory_file: Path,
    no_memory: bool,
) -> None:
    """Execute a YAML test definition."""
    try:
        test = schema.load(yaml_path)
    except Exception as e:  # schema/yaml errors
        _die(f"failed to load test definition: {e}")
        return

    console.print(f"[bold]Test:[/bold] {test.title}")

    resolved_llm = "stub" if dry_run else (
        llm_name or os.environ.get("OPEN_TESTERS_LLM") or "stub"
    )

    try:
        llm = get_provider(resolved_llm)
    except Exception as e:
        _die(f"failed to initialize LLM provider {resolved_llm!r}: {e}")
        return

    memories: list[dict] = []
    if not no_memory and memory_file.exists():
        try:
            memories = MemoryStore(memory_file).to_llm_context()
        except Exception as e:
            _die(f"failed to read memory file {memory_file}: {e}")
            return

    credentials_available: list[str] = []
    try:
        cred_store = CredentialStore()
        if cred_store.path.exists():
            credentials_available = [c.label for c in cred_store.list()]
    except Exception as e:
        _die(f"failed to list credentials: {e}")
        return

    try:
        viewport_tuple = _parse_viewport(viewport)
    except click.BadParameter as e:
        _die(str(e))
        return

    runner = Runner(
        test=test,
        llm=llm,
        output_root=output,
        memories=memories,
        credentials_available=credentials_available,
        viewport=viewport_tuple,
        max_actions_per_step=max_actions,
        headless=not headed,
    )

    try:
        result = asyncio.run(runner.run())
    except Exception as e:
        _die(f"runner crashed: {e}")
        return

    total_ms = sum(s.duration_ms for s in result.steps)
    status_color = "green" if result.status == "pass" else "red"
    console.print(
        f"Run [bold]{result.run_id}[/bold] — "
        f"[{status_color}]{result.status}[/{status_color}] in {total_ms}ms"
    )

    table = Table(show_header=True, header_style="bold")
    table.add_column("#", justify="right")
    table.add_column("type")
    table.add_column("title")
    table.add_column("status")
    table.add_column("duration_ms", justify="right")
    for step in result.steps:
        color = {"pass": "green", "fail": "red", "skipped": "yellow"}.get(
            step.status, "white"
        )
        table.add_row(
            str(step.step_index),
            step.type,
            step.title,
            f"[{color}]{step.status}[/{color}]",
            str(step.duration_ms),
        )
    console.print(table)
    console.print(f"Output: {result.output_dir}")

    sys.exit(1 if result.status == "fail" else 0)


# ---------------------------------------------------------------------------
# cred
# ---------------------------------------------------------------------------


@main.group()
def cred() -> None:
    """Manage encrypted credentials."""


@cred.command("add")
@click.argument("label")
@click.argument("kind")
@click.option(
    "--secret",
    "secrets",
    multiple=True,
    metavar="KEY=VALUE",
    help="Secret key/value pair; repeatable. Example: --secret username=alice.",
)
def cred_add(label: str, kind: str, secrets: tuple[str, ...]) -> None:
    """Add a credential. Prompts for the store passphrase unless
    OPEN_TESTERS_PASSPHRASE is set."""
    if kind not in VALID_KINDS:
        _die(
            f"unknown kind {kind!r}; expected one of {sorted(VALID_KINDS)}"
        )
        return
    if not secrets:
        _die("at least one --secret KEY=VALUE is required")
        return
    try:
        secret_dict = _parse_secrets(secrets)
    except click.BadParameter as e:
        _die(str(e))
        return
    try:
        summary = CredentialStore().add(label, kind, secret_dict)
    except Exception as e:
        _die(f"failed to add credential: {e}")
        return
    console.print(summary.id)


@cred.command("list")
def cred_list() -> None:
    """List credentials (metadata only)."""
    try:
        creds = CredentialStore().list()
    except Exception as e:
        _die(f"failed to list credentials: {e}")
        return
    if not creds:
        console.print("(no credentials)")
        return
    for c in creds:
        console.print(f"{c.id}  {c.label}  {c.kind}")


@cred.command("rm")
@click.argument("cred_id")
def cred_rm(cred_id: str) -> None:
    """Remove a credential by id."""
    try:
        removed = CredentialStore().remove(cred_id)
    except Exception as e:
        _die(f"failed to remove credential: {e}")
        return
    if removed:
        console.print("removed")
        sys.exit(0)
    console.print("not found")
    sys.exit(1)


# ---------------------------------------------------------------------------
# memory
# ---------------------------------------------------------------------------


_MEMORY_FILE_OPTION = click.option(
    "--memory-file",
    type=click.Path(path_type=Path),
    default=Path("open-testers.memory.json"),
    show_default=True,
)


@main.group()
def memory() -> None:
    """Manage the project memory store."""


@memory.command("add")
@click.argument("category")
@click.argument("title")
@click.argument("content")
@click.option(
    "--importance",
    type=click.Choice(["high", "medium", "low"]),
    default="medium",
    show_default=True,
)
@_MEMORY_FILE_OPTION
def memory_add(
    category: str,
    title: str,
    content: str,
    importance: str,
    memory_file: Path,
) -> None:
    """Add a memory entry."""
    try:
        m = MemoryStore(memory_file).add(category, title, content, importance)
    except Exception as e:
        _die(f"failed to add memory: {e}")
        return
    console.print(m.id)


@memory.command("list")
@_MEMORY_FILE_OPTION
def memory_list(memory_file: Path) -> None:
    """List memories sorted by importance."""
    try:
        entries = MemoryStore(memory_file).list()
    except Exception as e:
        _die(f"failed to list memories: {e}")
        return
    if not entries:
        console.print("(no memories)")
        return
    for m in entries:
        console.print(
            f"{m.id}  [{m.importance}]  {m.category}  {m.title}"
        )


@memory.command("rm")
@click.argument("memory_id")
@_MEMORY_FILE_OPTION
def memory_rm(memory_id: str, memory_file: Path) -> None:
    """Remove a memory by id."""
    try:
        removed = MemoryStore(memory_file).remove(memory_id)
    except Exception as e:
        _die(f"failed to remove memory: {e}")
        return
    if removed:
        console.print("removed")
        sys.exit(0)
    console.print("not found")
    sys.exit(1)


if __name__ == "__main__":
    main()
