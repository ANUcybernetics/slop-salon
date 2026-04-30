"""sprites.dev REST API client.

The exact endpoint paths and auth scheme are documented at https://sprites.dev.
This module gives the rest of the code a typed surface; if sprites.dev's API
changes, only this file needs updating.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

# Replace with the real sprites.dev base URL and endpoint paths from their docs.
SPRITES_BASE_URL = "https://api.sprites.dev"
ENDPOINT_CREATE = "/v1/sprites"
ENDPOINT_EXEC = "/v1/sprites/{sprite_id}/exec"
ENDPOINT_STATUS = "/v1/sprites/{sprite_id}"


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int


class SpritesClient:
    """Thin REST client for sprites.dev."""

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
        """Provision a new sprite. Returns the sprite ID."""
        response = self._client.post(
            ENDPOINT_CREATE,
            json={"name": name, "env": env_vars},
        )
        response.raise_for_status()
        return response.json()["id"]

    def exec(self, sprite_id: str, command: list[str]) -> ExecResult:
        """Execute a command in the sprite. Blocks until the sprite is ready."""
        response = self._client.post(
            ENDPOINT_EXEC.format(sprite_id=sprite_id),
            json={"command": command},
        )
        response.raise_for_status()
        data = response.json()
        return ExecResult(
            stdout=data.get("stdout", ""),
            stderr=data.get("stderr", ""),
            exit_code=data.get("exit_code", 0),
        )

    def get_status(self, sprite_id: str) -> str:
        """Return the sprite's lifecycle status (e.g., 'running', 'idle')."""
        response = self._client.get(ENDPOINT_STATUS.format(sprite_id=sprite_id))
        response.raise_for_status()
        return response.json()["status"]
