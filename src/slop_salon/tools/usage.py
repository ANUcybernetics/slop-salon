"""Per-tick token usage tally.

Sprite-side helper. Reads Claude Code's per-session JSONL transcripts at
`~/.claude/projects/-home-sprite-slop-salon-<agent>/*.jsonl` and emits one
JSON summary line per session. The admin-side `slop usage` command
fan-outs to each live sprite and aggregates.

Each tick is one Claude Code session (one JSONL file). One session makes
several API calls, and each call is written to the transcript as several
records --- see `tally_session`, which groups them by `message.id`.

Note the cache columns read 0 for the whole fleet: the self-hosted vLLM's
Anthropic-compatible endpoint doesn't report `cache_creation_input_tokens` or
`cache_read_input_tokens`, so every prompt token lands in `in_new` at full
input price. That is a gap in what vLLM *reports*, not evidence that nothing
is cached (it serves with `--enable-prefix-caching`), so treat these figures
as an uncached upper bound on what the same workload would cost on an API
that does report cache hits.
"""

from __future__ import annotations

import glob
import json
from pathlib import Path

import typer

# Notional Sonnet API pricing as of 2026-05 ($ per million tokens).
# Source: https://www.anthropic.com/pricing
#
# Inference is self-hosted vLLM, so no real dollars are spent; the "cost"
# is an API-equivalent effort proxy that makes ticks comparable across
# agents and over time. Real spend caps live elsewhere (Replicate).
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


_USAGE_FIELDS = {
    "in_new": "input_tokens",
    "cache_create": "cache_creation_input_tokens",
    "cache_read": "cache_read_input_tokens",
    "output": "output_tokens",
}


def tally_session(path: Path) -> dict:
    """Sum token usage across the API calls in one session JSONL file.

    Returns a dict with `session`, `mtime`, `in_new`, `cache_create`,
    `cache_read`, `output`, `turns` (API calls) and `blocks` (transcript
    records). Malformed JSON lines are skipped; lines whose `type` isn't
    `assistant` are ignored.

    **Group by `message.id`.** Claude Code writes one transcript record per
    *content block*, not per API call --- a single call answering with
    thinking + text + three tool_use blocks lands as five records, each
    stamped with that call's full `input_tokens` and only the last carrying
    its `output_tokens`. Summing per record therefore counted one 30k prompt
    five times: measured against six of rahel's sessions the old arithmetic
    overstated input by **3.2x** (and reported 109 "turns" for a tick that
    made 34 calls), which fed a fleet cost figure that was wrong by the same
    factor. Every record carries `message.id`, and records sharing one are the
    same call, so the id is the reliable key --- `stop_reason` also marks the
    terminal record but is absent on the rest, making it easy to mistake for
    missing data.

    Per id we take the **max** of each usage field rather than the first or
    last: `input_tokens` repeats identically across the group while
    `output_tokens` is 0 on every record but the terminal one, so max recovers
    both without depending on record order.
    """
    calls: dict[str, dict[str, int]] = {}
    blocks = 0
    with path.open() as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("type") != "assistant":
                continue
            blocks += 1
            message = d.get("message") or {}
            u = message.get("usage") or {}
            # No id (shouldn't happen, but don't silently drop the tokens):
            # fall back to a per-record key so it counts as its own call.
            key = message.get("id") or f"_anon{blocks}"
            call = calls.setdefault(key, dict.fromkeys(_USAGE_FIELDS, 0))
            for field, wire in _USAGE_FIELDS.items():
                call[field] = max(call[field], u.get(wire) or 0)

    stats: dict = {
        "session": path.stem[:8],
        "mtime": int(path.stat().st_mtime),
        "turns": len(calls),
        "blocks": blocks,
    }
    for field in _USAGE_FIELDS:
        stats[field] = sum(call[field] for call in calls.values())
    return stats


def tally_dir(agent: str, root: Path | None = None) -> list[dict]:
    """Tally every session for one agent. Sorted by mtime ascending."""
    base = (root or SPRITE_PROJECTS_ROOT) / f"-home-sprite-slop-salon-{agent}"
    files = sorted(map(Path, glob.glob(str(base / "*.jsonl"))), key=lambda p: p.stat().st_mtime)
    return [tally_session(p) for p in files]


def session_cost(stats: dict) -> float:
    """Notional API-equivalent $ for one session (see pricing note above)."""
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
