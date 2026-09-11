"""The environment one tick runs in.

Nothing durable lives in a sprite: identity, endpoint, model and secrets are
assembled here from the registry and the admin box's env, and handed to
`slop-tick` through `sprite exec --env` for the life of one command.
"""

from __future__ import annotations

import os
import shlex
import tomllib
from collections.abc import Mapping
from pathlib import Path

from .config import Agent, Config

# Generous next to a healthy turn, but a hung request must not eat the tick's
# whole 2h cap.
API_TIMEOUT_MS = "600000"
# Any non-empty value: Claude Code refuses to start without a credential, and
# the gateway replaces whatever is sent.
CONNECTOR_PLACEHOLDER_TOKEN = "sprite"

# The remote shell echoes this before `slop-tick`, so finding it in a result's
# stdout is proof the sprite accepted the session. A failed exec without it
# never reached the tick --- the sprite was unreachable, or still resuming from
# cold --- and can be run again; a failed exec with it did reach the tick,
# whose `claude` may still be running in the sprite after the client gives up,
# so running it again would tick the agent twice.
SESSION_MARKER = "slop-exec: session up"


def tick_command(prompt: str) -> list[str]:
    """The shell one tick runs in the sprite: report for duty, then tick."""
    return [
        "bash",
        "-lc",
        f"echo {shlex.quote(SESSION_MARKER)}; slop-tick {shlex.quote(prompt)}",
    ]


def tick_output(stdout: str) -> str:
    """`stdout` without the session marker, for anything a human reads."""
    kept = [line for line in stdout.splitlines() if line.strip() != SESSION_MARKER]
    return "\n".join(kept)


def bsky_password(name: str, secrets_path: str | Path = "secrets.toml") -> str:
    """The agent's Bluesky app password from the gitignored per-agent secrets file."""
    p = Path(secrets_path)
    if not p.exists():
        raise RuntimeError(f"{p} not found; copy secrets.example.toml and fill it in")
    with p.open("rb") as f:
        data = tomllib.load(f)
    password = data.get("agents", {}).get(name, {}).get("bsky_password", "")
    if not password:
        raise RuntimeError(f"no bsky_password for {name!r} in {p}")
    return password


def _require(environ: Mapping[str, str], key: str) -> str:
    value = environ.get(key)
    if not value:
        raise RuntimeError(f"{key} is not set in the admin env (~/.config/mise/config.local.toml)")
    return value


def tick_env(
    config: Config,
    agent: Agent,
    environ: Mapping[str, str] | None = None,
    secrets_path: str | Path = "secrets.toml",
) -> dict[str, str]:
    """Everything `slop-tick` and the in-sprite tools read from the environment.

    Raises on the admin box if a secret is missing, so a half-configured fleet
    fails here rather than as a dead tick. Values must not contain commas
    (`sprite exec --env` is comma-delimited), so list-valued vars are
    space-separated.
    """
    src = os.environ if environ is None else environ
    provider = config.provider_for(agent.name)

    if provider.auth == "connector":
        token = CONNECTOR_PLACEHOLDER_TOKEN
    elif provider.auth == "secret_env":
        token = _require(src, provider.secret_env)
    else:
        raise NotImplementedError(
            f"provider {provider.name!r}: auth = 'credentials' is declared but not built"
        )

    siblings = [config.agents[s].handle for s in agent.siblings]
    collective = [a.handle for a in config.agents.values()]
    env = {
        "AGENT_NAME": agent.name,
        "BSKY_HANDLE": agent.handle,
        "BSKY_PASSWORD": bsky_password(agent.name, secrets_path),
        "GH_TOKEN": _require(src, "SLOP_GH_TOKEN"),
        "REPLICATE_API_TOKEN": _require(src, "SLOP_REPLICATE_API_TOKEN"),
        "ANTHROPIC_BASE_URL": provider.base_url,
        "ANTHROPIC_AUTH_TOKEN": token,
        # Explicitly empty, not merely absent, or Claude Code may fall back to
        # an Anthropic login.
        "ANTHROPIC_API_KEY": "",
        "ANTHROPIC_MODEL": provider.model,
        "ANTHROPIC_SMALL_FAST_MODEL": provider.model,
        "API_TIMEOUT_MS": API_TIMEOUT_MS,
        # The provenance stamp `bsky` writes into every post, and the salon
        # boundary it enforces on follows, replies and quotes.
        "SLOP_MODEL": provider.model_id,
        "SLOP_SALON": agent.salon,
        "SLOP_SIBLINGS": " ".join(siblings),
        "SLOP_COLLECTIVE": " ".join(collective),
    }
    if provider.context_window:
        env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = str(provider.context_window)
    return env
