"""Per-tick token usage tally.

Sprite-side helper. Reads Claude Code's per-session JSONL transcripts at
`~/.claude/projects/-home-sprite-slop-salon-<agent>/*.jsonl` and emits one
JSON summary line per session. The admin-side `slop usage` command
fan-outs to each live sprite and aggregates.

Each tick is one Claude Code session (one JSONL file). One session makes
several API calls, and each call is written to the transcript as several
records --- see `tally_session`, which groups them by `message.id`.

Both runners are read (see `tally_dir`), because which one an agent uses is a
per-agent provider choice that can change between ticks.

The cache columns read 0 for any agent on the **vllm** provider: the self-hosted
endpoint doesn't report `cache_creation_input_tokens` or
`cache_read_input_tokens`, so every prompt token lands in `in_new` at full input
price. That is a gap in what vLLM *reports*, not evidence that nothing is cached
(it serves with `--enable-prefix-caching`), so treat those figures as an uncached
upper bound. A hosted provider does report hits, so a non-zero `cache_read` after
a provider swap is the first sign the swap actually took.

This tool emits **raw token counts only**. Pricing lives in the provider
registry and is applied admin-side by `slop usage`, because a sprite has no way
to know what its provider charges --- and a hardcoded guess is worse than no
figure, since it still reads as authoritative.
"""

from __future__ import annotations

import glob
import json
from pathlib import Path

import typer

from slop_salon.config import Pricing

SPRITE_PROJECTS_ROOT = Path("/home/sprite/.claude/projects")
SPRITE_CODEX_SESSIONS_ROOT = Path("/home/sprite/.codex/sessions")

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
        "runner": "claude",
    }
    for field in _USAGE_FIELDS:
        stats[field] = sum(call[field] for call in calls.values())
    return stats


def tally_codex_session(path: Path) -> dict:
    """Sum token usage across one codex rollout file.

    Codex records usage in `payload.type == "token_count"` events carrying an
    `info.total_token_usage` (cumulative over the session) and an
    `info.last_token_usage` (that one request). Two traps, both the mirror of
    the `message.id` overcount in `tally_session` above:

    **Take the last total, never a sum.** The totals are cumulative, so adding
    them up counts the whole session once per request --- an order-of-magnitude
    error that looks entirely plausible in a table.

    **`input_tokens` already includes `cached_input_tokens`.** Claude reports
    them as disjoint buckets; codex reports the total plus how much of it was
    cached. Subtract, or a cached-heavy session appears to have paid full price
    for the same tokens twice.

    Returns the same shape as `tally_session` so both runners share the table.
    `turns` counts requests (token_count events with a per-request delta).
    """
    totals: dict[str, int] = {}
    turns = 0
    blocks = 0
    rate: dict = {}
    with path.open() as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            blocks += 1
            payload = d.get("payload") or {}
            if payload.get("type") != "token_count":
                continue
            info = payload.get("info") or {}
            total = info.get("total_token_usage") or {}
            if total:
                totals = total  # cumulative: last one wins
            if info.get("last_token_usage"):
                turns += 1
            if payload.get("rate_limits"):
                rate = payload["rate_limits"]

    cached = totals.get("cached_input_tokens") or 0
    stats: dict = {
        "session": path.stem[-8:],
        "mtime": int(path.stat().st_mtime),
        "turns": turns,
        "blocks": blocks,
        "runner": "codex",
        # input_tokens is inclusive of cached; max(0, ...) guards a malformed
        # pair rather than reporting a negative token count.
        "in_new": max(0, (totals.get("input_tokens") or 0) - cached),
        "cache_create": totals.get("cache_write_input_tokens") or 0,
        "cache_read": cached,
        "output": totals.get("output_tokens") or 0,
    }
    # Subscription headroom, which is the number that actually decides whether a
    # plan can carry six agents --- task-16 could only argue it from token
    # arithmetic. Codex reports it directly, so pass it through.
    primary = (rate or {}).get("primary") or {}
    if primary.get("used_percent") is not None:
        stats["limit_pct"] = primary["used_percent"]
        stats["limit_window_min"] = primary.get("window_minutes")
    if (rate or {}).get("plan_type"):
        stats["plan_type"] = rate["plan_type"]
    return stats


def tally_dir(agent: str, root: Path | None = None, codex_root: Path | None = None) -> list[dict]:
    """Tally every session for one agent, both runners. Sorted by mtime ascending.

    Detected from what is on disk rather than from `SLOP_RUNNER`: this runs via
    a bare `sprite exec`, which does not source `~/.slop-provider`, so the env
    is not available here. Reading both also means the ticks either side of a
    provider swap stay visible in one table.
    """
    base = (root or SPRITE_PROJECTS_ROOT) / f"-home-sprite-slop-salon-{agent}"
    rows = [(p, tally_session) for p in map(Path, glob.glob(str(base / "*.jsonl")))]
    codex_base = codex_root or SPRITE_CODEX_SESSIONS_ROOT
    if codex_base.exists():
        rows += [(p, tally_codex_session) for p in codex_base.rglob("rollout-*.jsonl")]
    rows.sort(key=lambda pair: pair[0].stat().st_mtime)
    return [fn(p) for p, fn in rows]


def session_cost(stats: dict, pricing: Pricing) -> float:
    """What one session actually cost, at `pricing`'s per-million-token rates."""
    return (
        stats["in_new"] * pricing.input
        + stats["cache_create"] * pricing.cache_write
        + stats["cache_read"] * pricing.cache_read
        + stats["output"] * pricing.output
    ) / 1_000_000


@app.command()
def tally(
    agent: str = typer.Argument(..., help="Agent name (matches the slop-salon-<name> dir)"),
):
    """Emit one JSON line per session for the given agent --- raw token counts only.

    Deliberately no dollar figure: the sprite has no idea what its provider
    charges, and the previous version guessed with hardcoded Sonnet rates. That
    guess reported a real DeepSeek wake as $12.36 against an actual $0.20. The
    admin-side `slop usage` prices these counts from the provider registry,
    which is the only place that knows the rates.
    """
    for stats in tally_dir(agent):
        stats["agent"] = agent
        typer.echo(json.dumps(stats))
