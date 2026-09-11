"""Destroy and rebuild one agent's sprite from its repo.

The remedy for a wedged sprite (the platform's idle i/o-timeout), run by hand
as `slop recreate` or by `slop wake` after a second consecutive wedge. The
agent's state is whatever its repo holds; the sprite-local `assets/` cache is
lost, by design.
"""

from __future__ import annotations

import time
from pathlib import Path

import typer

from .config import load_config
from .provision import bootstrap_sprite
from .sprites import AGENT_LABEL, SpritesClient


def recreate(
    name: str,
    config_path: str | Path = "slop_salon.toml",
    sprites: SpritesClient | None = None,
) -> None:
    config = load_config(config_path)
    if name not in config.agents:
        raise ValueError(f"agent {name!r} missing from {config_path}")
    agent = config.agents[name]
    if not agent.sprite_id:
        raise ValueError(f"{name} has no sprite_id; use `slop new`, not a recreate")
    # Anything that can fail on a credential runs before the destroy: a wedged
    # sprite that still exists gets another go next wake, a destroyed one does not.
    from .tick import tick_env

    tick_env(config, agent)
    sprites = sprites or SpritesClient()

    typer.echo(f"[1/3] Destroying sprite {agent.sprite_id!r}")
    sprites.destroy_sprite(agent.sprite_id)
    # The name is released asynchronously; a create straight after the
    # destroy can race it.
    time.sleep(5)

    typer.echo(f"[2/3] Creating sprite {agent.sprite_id!r}")
    sprites.create_sprite(agent.sprite_id, labels=[AGENT_LABEL, f"salon={agent.salon}"])

    typer.echo("[3/3] Bootstrapping: policy, clone, setup.sh, claude pin")
    bootstrap_sprite(sprites, config, agent)
    typer.echo(f"Recreated {name}.")
