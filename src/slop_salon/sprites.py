"""sprites.dev client.

Two surfaces:

- HTTP for endpoints that take a JSON envelope (create, get_status). The REST
  API is documented at <https://docs.sprites.dev>; this module covers what we
  actually drive from provisioning code.
- A subprocess shell-out to the `sprite` CLI for `exec`. The REST exec path is
  a streaming-bytes channel without an exit-code envelope; the canonical
  protocol is the WebSocket one the CLI implements. We rely on the CLI here
  rather than building a WS client.

Sprites are addressed by **name** (the slug used at creation, e.g. `lou`).
The API also returns an `id` field (a UUID-prefixed string), but `name` is
what the CLI and most of our code use, and what we store as `sprite_id` in
`slop_salon.toml`.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

import httpx

SPRITES_BASE_URL = "https://api.sprites.dev/v1"
ENDPOINT_CREATE = "/sprites"
ENDPOINT_EXEC = "/sprites/{name}/exec"
ENDPOINT_STATUS = "/sprites/{name}"


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int


class SpritesClient:
    """sprites.dev client: HTTP for create/status, CLI shell-out for exec."""

    def __init__(self, base_url: str = SPRITES_BASE_URL):
        token = os.environ.get("SPRITES_API_TOKEN")
        if not token:
            raise RuntimeError("SPRITES_API_TOKEN env var is required")
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(60.0),
        )

    def create_sprite(self, name: str, env_vars: dict[str, str]) -> str:
        """Provision a new sprite. Returns the sprite's name (used for addressing)."""
        response = self._client.post(
            ENDPOINT_CREATE,
            json={"name": name, "env": env_vars},
        )
        response.raise_for_status()
        return response.json()["name"]

    def exec(self, sprite_id: str, command: list[str]) -> ExecResult:
        """Execute a command in the sprite via the `sprite` CLI.

        `sprite_id` here is the sprite's name. The CLI handles its own auth via
        `~/.sprites/keyring/` (set up once with `sprite auth setup --token`).
        """
        result = subprocess.run(
            ["sprite", "exec", "-s", sprite_id, "--", *command],
            capture_output=True,
            text=True,
        )
        return ExecResult(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.returncode,
        )

    def get_status(self, sprite_id: str) -> str:
        """Return the sprite's lifecycle status (e.g. `cold`, `warm`, `running`)."""
        response = self._client.get(ENDPOINT_STATUS.format(name=sprite_id))
        response.raise_for_status()
        return response.json()["status"]
