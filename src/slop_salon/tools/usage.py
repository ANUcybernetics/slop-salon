"""Per-tick token usage tally.

Sprite-side helper. Reads Claude Code's per-session JSONL transcripts at
`~/.claude/projects/-home-sprite-slop-salon-<agent>/*.jsonl` and emits one
JSON summary line per session. The admin-side `slop usage` command
fan-outs to each live sprite and aggregates.

Each tick is one Claude Code session (one JSONL file). Within a session,
many assistant turns share the cache; cache reads within a session are
cheap. Across ticks, the 5-minute cache TTL means cache_creation is paid
again on every tick.
"""

from __future__ import annotations

import glob
import json
from pathlib import Path

import typer

# Sonnet pricing as of 2026-05 ($ per million tokens).
# Source: https://www.anthropic.com/pricing
PRICE_INPUT = 3.00
PRICE_OUTPUT = 15.00
PRICE_CACHE_CREATE = 3.75
PRICE_CACHE_READ = 0.30

SPRITE_PROJECTS_ROOT = Path("/home/sprite/.claude/projects")

app = typer.Typer(
    add_completion=False,
    help="Per-tick token usage tally for one agent (sprite-side helper).",
    no_args_is_help=True,
)


@app.callback()
def _main() -> None:
    """Force multi-command mode so `slop-usage tally <agent>` works as expected."""


def tally_session(path: Path) -> dict:
    """Sum token usage across all assistant turns in one session JSONL file.

    Returns a dict with `session`, `mtime`, `in_new`, `cache_create`,
    `cache_read`, `output`, `turns`. Malformed JSON lines are skipped.
    Lines whose `type` isn't `assistant` are ignored.
    """
    stats = {
        "session": path.stem[:8],
        "mtime": int(path.stat().st_mtime),
        "in_new": 0,
        "cache_create": 0,
        "cache_read": 0,
        "output": 0,
        "turns": 0,
    }
    with path.open() as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("type") != "assistant":
                continue
            stats["turns"] += 1
            u = (d.get("message") or {}).get("usage") or {}
            stats["in_new"] += u.get("input_tokens") or 0
            stats["cache_create"] += u.get("cache_creation_input_tokens") or 0
            stats["cache_read"] += u.get("cache_read_input_tokens") or 0
            stats["output"] += u.get("output_tokens") or 0
    return stats


def tally_dir(agent: str, root: Path | None = None) -> list[dict]:
    """Tally every session for one agent. Sorted by mtime ascending."""
    base = (root or SPRITE_PROJECTS_ROOT) / f"-home-sprite-slop-salon-{agent}"
    files = sorted(map(Path, glob.glob(str(base / "*.jsonl"))), key=lambda p: p.stat().st_mtime)
    return [tally_session(p) for p in files]


def session_cost(stats: dict) -> float:
    """Approximate $ cost for one session at current Sonnet pricing."""
    return (
        stats["in_new"] * PRICE_INPUT
        + stats["cache_create"] * PRICE_CACHE_CREATE
        + stats["cache_read"] * PRICE_CACHE_READ
        + stats["output"] * PRICE_OUTPUT
    ) / 1_000_000


@app.command()
def tally(
    agent: str = typer.Argument(..., help="Agent name (matches the slop-salon-<name> dir)"),
):
    """Emit one JSON line per session for the given agent."""
    for stats in tally_dir(agent):
        stats["agent"] = agent
        stats["cost_usd"] = round(session_cost(stats), 6)
        typer.echo(json.dumps(stats))
