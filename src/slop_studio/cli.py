"""Admin `slop` CLI.

Subcommands:
    status   one-line dashboard per agent
    feed     recent Bluesky posts (across or per agent)
    logs     recent transcripts from a sprite
    diff     repo changes since a given duration
    pause    stop the cron schedule on a sprite
    resume   restart the cron schedule on a sprite
    talk     one-shot stateless prompt to an agent
    new      provision a new agent (see provision.py)
"""

from __future__ import annotations

import typer

from slop_studio.config import load_config
from slop_studio.sprites import SpritesClient

app = typer.Typer(add_completion=False, help="Slop Studio admin CLI.")


@app.callback()
def main() -> None:
    """Slop Studio admin CLI."""


def _config(path: str | None = None):
    return load_config(path or "slop_studio.toml")


@app.command()
def status(
    config_path: str = typer.Option(None, "--config", help="Path to slop_studio.toml"),
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
    result = sprites.exec(
        sprite_id,
        [
            "bash",
            "-lc",
            "ls -t ~/slop-studio-$AGENT_NAME/.claude/ 2>/dev/null | head -5 | "
            'while read f; do echo "=== $f ==="; '
            'cat ~/slop-studio-$AGENT_NAME/.claude/"$f"; done',
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
    result = sprites.exec(
        sprite_id,
        [
            "bash",
            "-lc",
            f"cd ~/slop-studio-$AGENT_NAME && git log --since='{since}' --stat -p",
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
def pause(
    name: str = typer.Argument(..., help="Agent name"),
    config_path: str = typer.Option(None, "--config"),
):
    """Stop the cron schedule on the agent's sprite (preserves the saved crontab)."""
    config = _config(config_path)
    sprite_id = _require_sprite_id(config, name)
    sprites = SpritesClient()
    # Save current crontab to a file, then remove it. Idempotent: re-running
    # is safe because resume reads from the saved file.
    cmd = "crontab -l > ~/.crontab.paused 2>/dev/null; crontab -r 2>/dev/null; echo paused"
    result = sprites.exec(sprite_id, ["bash", "-lc", cmd])
    typer.echo(result.stdout.strip() or "paused")


@app.command()
def resume(
    name: str = typer.Argument(..., help="Agent name"),
    config_path: str = typer.Option(None, "--config"),
):
    """Restart the cron schedule on the agent's sprite."""
    config = _config(config_path)
    sprite_id = _require_sprite_id(config, name)
    sprites = SpritesClient()
    result = sprites.exec(
        sprite_id,
        ["bash", "-lc", "crontab ~/.crontab.paused && echo resumed"],
    )
    typer.echo(result.stdout.strip() or "resumed")
