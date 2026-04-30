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
