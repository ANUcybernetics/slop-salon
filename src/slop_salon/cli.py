"""Admin `slop` CLI.

Subcommands:
    status   one-line dashboard per agent
    feed     recent Bluesky posts (across or per agent)
    logs     recent transcripts from a sprite
    diff     repo changes since a given duration
    drift    template vs. live-repo divergence per agent
    talk     one-shot stateless prompt to an agent
    new      provision a new agent (see provision.py)
"""

from __future__ import annotations

import difflib
import shlex
import subprocess
import tempfile
from pathlib import Path

import typer

from slop_salon.config import load_config
from slop_salon.provision import _build_template_files, provision_agent
from slop_salon.sprites import SpritesClient

app = typer.Typer(add_completion=False, help="Slop Salon admin CLI.")


@app.callback()
def main() -> None:
    """Slop Salon admin CLI."""


def _config(path: str | None = None):
    return load_config(path or "slop_salon.toml")


@app.command()
def status(
    config_path: str = typer.Option(None, "--config", help="Path to slop_salon.toml"),
):
    """Print one line per agent: name, handle, sprite state."""
    config = _config(config_path)
    sprites = SpritesClient()
    for name, agent in config.agents.items():
        if agent.sprite_id:
            try:
                sprite_state = sprites.get_status(agent.sprite_id)
            except Exception as e:
                sprite_state = f"error: {e}"
        else:
            sprite_state = "not provisioned"
        typer.echo(f"{name:12s}  {agent.handle:30s}  {sprite_state}")


def _require_sprite_id(config, agent_name: str) -> str:
    agent = config.agents.get(agent_name)
    if agent is None:
        typer.echo(f"error: unknown agent {agent_name!r}", err=True)
        raise typer.Exit(code=1)
    if not agent.sprite_id:
        typer.echo(f"error: agent {agent_name!r} has no sprite_id (not provisioned?)", err=True)
        raise typer.Exit(code=1)
    return agent.sprite_id


@app.command()
def logs(
    name: str = typer.Argument(..., help="Agent name"),
    config_path: str = typer.Option(None, "--config"),
):
    """Print recent claude transcripts from the agent's sprite."""
    config = _config(config_path)
    sprite_id = _require_sprite_id(config, name)
    sprites = SpritesClient()
    # `.claude/` holds session transcripts; tail the most recent.
    # Substitute the agent name client-side rather than relying on
    # AGENT_NAME being in the sprite's interactive-shell env.
    quoted_name = shlex.quote(name)
    result = sprites.exec(
        sprite_id,
        [
            "bash",
            "-lc",
            f"ls -t ~/slop-salon-{quoted_name}/.claude/ 2>/dev/null | head -5 | "
            'while read f; do echo "=== $f ==="; '
            f'cat ~/slop-salon-{quoted_name}/.claude/"$f"; done',
        ],
    )
    typer.echo(result.stdout)
    if result.stderr:
        typer.echo(result.stderr, err=True)


@app.command()
def diff(
    name: str = typer.Argument(..., help="Agent name"),
    since: str = typer.Option(
        "1.day",
        "--since",
        help="Git revspec or duration (e.g. '1.day', '2.hours')",
    ),
    config_path: str = typer.Option(None, "--config"),
):
    """Show recent repo changes from the agent's sprite."""
    config = _config(config_path)
    sprite_id = _require_sprite_id(config, name)
    sprites = SpritesClient()
    quoted_name = shlex.quote(name)
    quoted_since = shlex.quote(since)
    result = sprites.exec(
        sprite_id,
        [
            "bash",
            "-lc",
            f"cd ~/slop-salon-{quoted_name} && git log --since={quoted_since} --stat -p",
        ],
    )
    typer.echo(result.stdout)
    if result.stderr:
        typer.echo(result.stderr, err=True)


def atproto_client_for_feed():
    """Build an unauthenticated atproto Client for reading public feeds.

    Wrapped in a function so tests can mock the factory.
    """
    from atproto import Client

    return Client()


@app.command()
def feed(
    name: str = typer.Argument(None, help="Agent name (default: all agents)"),
    limit: int = typer.Option(10, "--limit", help="Posts per agent"),
    config_path: str = typer.Option(None, "--config"),
):
    """Print recent Bluesky posts from one agent (or all agents)."""
    config = _config(config_path)
    targets = [config.agents[name]] if name else list(config.agents.values())
    client = atproto_client_for_feed()

    for agent in targets:
        typer.echo(f"=== {agent.name} ({agent.handle}) ===")
        try:
            response = client.get_author_feed(actor=agent.handle, limit=limit)
        except Exception as e:
            typer.echo(f"  (error: {e})")
            continue
        for item in response.feed:
            text = getattr(item.post.record, "text", "")
            indexed = getattr(item.post, "indexed_at", "")
            typer.echo(f"  [{indexed}] {text}")


@app.command()
def talk(
    name: str = typer.Argument(..., help="Agent name"),
    prompt: str = typer.Argument(..., help="One-shot prompt for the agent"),
    config_path: str = typer.Option(None, "--config"),
):
    """Send a one-shot stateless prompt to an agent. Runs as a tick."""
    config = _config(config_path)
    sprite_id = _require_sprite_id(config, name)
    sprites = SpritesClient()
    quoted = shlex.quote(prompt)
    result = sprites.exec(
        sprite_id,
        ["bash", "-lc", f"slop-tick {quoted}"],
    )
    typer.echo(result.stdout)
    if result.stderr:
        typer.echo(result.stderr, err=True)
    if result.exit_code != 0:
        raise typer.Exit(code=result.exit_code)


DRIFT_DEFAULT_FILES = ("SOUL.md", "CLAUDE.md", "slop-tick")


def _fetch_live_files(repo: str, files: list[str]) -> dict[str, str | None]:
    """Shallow-clone `repo` and return {filename: content or None if missing}."""
    with tempfile.TemporaryDirectory() as td:
        clone_dir = Path(td) / "repo"
        subprocess.run(
            ["gh", "repo", "clone", repo, str(clone_dir), "--", "--depth=1"],
            check=True,
            capture_output=True,
        )
        return {f: (clone_dir / f).read_text() if (clone_dir / f).exists() else None for f in files}


@app.command()
def drift(
    name: str = typer.Argument(None, help="Agent name (omit to scan all)"),
    file: list[str] = typer.Option(
        None, "--file", "-f", help=f"Files to check (default: {', '.join(DRIFT_DEFAULT_FILES)})"
    ),
    templates_dir: str = typer.Option("templates", "--templates"),
    soul_path: str = typer.Option("SOUL.md", "--soul"),
    config_path: str = typer.Option(None, "--config"),
):
    """Diff live agent repos against the canonical templates.

    Use to spot SOUL.md tampering (should always be clean) and to inspect
    how each agent has edited its own CLAUDE.md (drift is expected there).
    """
    config = _config(config_path)
    if name:
        if name not in config.agents:
            typer.echo(f"error: unknown agent {name!r}", err=True)
            raise typer.Exit(code=1)
        targets = [config.agents[name]]
    else:
        targets = list(config.agents.values())

    files = list(file) if file else list(DRIFT_DEFAULT_FILES)

    for i, agent in enumerate(targets):
        if i:
            typer.echo("")
        sibling_name = agent.siblings[0] if agent.siblings else ""
        sibling_handle = config.agents[sibling_name].handle if sibling_name in config.agents else ""
        expected = _build_template_files(
            Path(templates_dir),
            Path(soul_path),
            agent.name,
            agent.handle,
            sibling_name,
            sibling_handle,
        )
        try:
            live = _fetch_live_files(agent.github_repo, files)
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr.decode().strip() if e.stderr else "").splitlines()
            tail = stderr[-1] if stderr else f"exit {e.returncode}"
            typer.echo(f"{agent.name}\n  could not fetch {agent.github_repo}: {tail}")
            continue
        typer.echo(agent.name)
        for f in files:
            exp = expected.get(f)
            got = live.get(f)
            if exp is None:
                typer.echo(f"  {f:14s}  no template")
                continue
            if got is None:
                typer.echo(f"  {f:14s}  MISSING from live repo")
                continue
            if exp == got:
                typer.echo(f"  {f:14s}  clean")
                continue
            diff_lines = list(
                difflib.unified_diff(
                    exp.splitlines(keepends=True),
                    got.splitlines(keepends=True),
                    fromfile=f"template/{f}",
                    tofile=f"{agent.name}/{f}",
                )
            )
            added = sum(1 for ln in diff_lines if ln.startswith("+") and not ln.startswith("+++"))
            removed = sum(1 for ln in diff_lines if ln.startswith("-") and not ln.startswith("---"))
            typer.echo(f"  {f:14s}  drift (+{added}/-{removed})")
            for line in diff_lines:
                typer.echo(f"    {line.rstrip()}")


@app.command()
def new(
    name: str = typer.Argument(..., help="New agent name (must already be in slop_salon.toml)"),
    yes_dns: bool = typer.Option(
        False, "--yes-dns", help="Skip the manual DNS confirmation prompt"
    ),
    config_path: str = typer.Option(None, "--config"),
):
    """Provision a new agent end-to-end."""
    provision_agent(
        name,
        config_path=config_path or "slop_salon.toml",
        skip_dns_confirm=yes_dns,
    )
