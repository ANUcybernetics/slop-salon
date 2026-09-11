"""sprites.dev client.

HTTP for the endpoints that take a JSON envelope (create, destroy, status,
labels, network policy); a shell-out to the `sprite` CLI for `exec`, whose
canonical protocol is the WebSocket one the CLI implements. Sprites are
addressed by name (`lou`), which is what `slop_salon.toml` stores as
`sprite_id`.
"""

from __future__ import annotations

import functools
import os
import subprocess
from dataclasses import dataclass
from typing import Protocol

import httpx

SPRITES_BASE_URL = "https://api.sprites.dev/v1"

# Every agent sprite carries this label; the connectors' access policies are
# gated on it, so a sprite without it cannot reach the model.
AGENT_LABEL = "slop"


@functools.cache
def _exec_flags() -> list[str]:
    """Extra `sprite exec` flags this CLI understands.

    `--no-port-forward` arrived in rc48: without it the CLI forwards any port
    the remote command opens back to the admin box, which an unattended wake of
    nine concurrent ticks has no use for. Asked of `--help` rather than
    hardcoded, so an older CLI still runs rather than failing every tick on an
    unknown flag.
    """
    try:
        help_text = subprocess.run(
            ["sprite", "exec", "--help"], capture_output=True, text=True, timeout=30
        ).stdout
    except OSError, subprocess.SubprocessError:
        return []
    return ["--no-port-forward"] if "--no-port-forward" in help_text else []


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int


class SpriteExecutor(Protocol):
    def exec(
        self, sprite_id: str, command: list[str], env: dict[str, str] | None = None
    ) -> ExecResult: ...


class SpritesClient:
    def __init__(self, base_url: str = SPRITES_BASE_URL):
        token = os.environ.get("SPRITES_API_TOKEN")
        if not token:
            raise RuntimeError("SPRITES_API_TOKEN env var is required")
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(60.0),
        )

    def create_sprite(self, name: str, labels: list[str] | None = None) -> str:
        """Create a sprite. Returns its name."""
        body: dict = {"name": name}
        if labels:
            body["labels"] = labels
        response = self._client.post("/sprites", json=body)
        response.raise_for_status()
        return response.json()["name"]

    def destroy_sprite(self, name: str) -> None:
        response = self._client.delete(f"/sprites/{name}")
        if response.status_code != 404:
            response.raise_for_status()

    def set_labels(self, name: str, labels: list[str]) -> None:
        response = self._client.put(f"/sprites/{name}", json={"labels": labels})
        response.raise_for_status()

    def set_network_policy(self, name: str, rules: list[dict]) -> None:
        """Replace the sprite's DNS egress allowlist. Must be done from outside
        the sprite; existing connections to newly-blocked domains are cut."""
        response = self._client.post(f"/sprites/{name}/policy/network", json={"rules": rules})
        response.raise_for_status()

    def get_status(self, name: str) -> str:
        response = self._client.get(f"/sprites/{name}")
        response.raise_for_status()
        return response.json()["status"]

    def exec(
        self, sprite_id: str, command: list[str], env: dict[str, str] | None = None
    ) -> ExecResult:
        """Run `command` in the sprite via the CLI, with `env` in its environment.

        The CLI takes env as `KEY=value,KEY2=value2`, so no value may contain a
        comma; `tick.tick_env` guarantees that for the values it builds.
        """
        args = ["sprite", "exec", "-s", sprite_id, *_exec_flags()]
        if env:
            for key, value in env.items():
                if "," in value:
                    raise ValueError(
                        f"env var {key} contains a comma, which `sprite exec --env` cannot carry"
                    )
            args += ["--env", ",".join(f"{k}={v}" for k, v in env.items())]
        result = subprocess.run([*args, "--", *command], capture_output=True, text=True)
        return ExecResult(stdout=result.stdout, stderr=result.stderr, exit_code=result.returncode)
