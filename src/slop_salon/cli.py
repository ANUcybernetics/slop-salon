"""Admin `slop` CLI.

Subcommands:
    status         one-line dashboard per agent
    feed           recent Bluesky posts (across or per agent)
    logs           recent transcripts from a sprite
    diff           repo changes since a given duration
    drift          template vs. live-repo divergence per agent
    talk           one-shot stateless prompt to an agent
    wake           fire a tick at every live agent in parallel
    usage          per-tick token and cost tally across live agents
    new            provision a new agent (see provision.py)
    sync-siblings  backfill missing sibling entries in live SIBLINGS.md
"""

from __future__ import annotations

import difflib
import json
import os
import re
import shlex
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import mean, median

import httpx
import typer

from slop_salon.config import load_config
from slop_salon.provision import (
    SLOP_SALON_REPO,
    _build_install_ambient_hook_cmd,
    _build_template_files,
    _render_sibling_block,
    provision_agent,
    resolve_secrets,
)
from slop_salon.sprites import SpritesClient

app = typer.Typer(add_completion=False, help="Slop Salon admin CLI.")


@app.callback()
def main() -> None:
    """Slop Salon admin CLI."""


def _config(path: str | None = None):
    return load_config(path or "slop_salon.toml")


@app.command()
def status(
    config_path: str = typer.Option(None, "--config", help="Path to slop_salon.toml"),
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
    # Substitute the agent name client-side rather than relying on
    # AGENT_NAME being in the sprite's interactive-shell env.
    quoted_name = shlex.quote(name)
    result = sprites.exec(
        sprite_id,
        [
            "bash",
            "-lc",
            f"ls -t ~/slop-salon-{quoted_name}/.claude/ 2>/dev/null | head -5 | "
            'while read f; do echo "=== $f ==="; '
            f'cat ~/slop-salon-{quoted_name}/.claude/"$f"; done',
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
    quoted_name = shlex.quote(name)
    quoted_since = shlex.quote(since)
    result = sprites.exec(
        sprite_id,
        [
            "bash",
            "-lc",
            f"cd ~/slop-salon-{quoted_name} && git log --since={quoted_since} --stat -p",
        ],
    )
    typer.echo(result.stdout)
    if result.stderr:
        typer.echo(result.stderr, err=True)


APPVIEW = "https://public.api.bsky.app"


def _fetch_author_feed(handle: str, limit: int) -> list[dict]:
    """Fetch recent posts for `handle` from the public Bluesky AppView (unauthenticated)."""
    response = httpx.get(
        f"{APPVIEW}/xrpc/app.bsky.feed.getAuthorFeed",
        params={"actor": handle, "limit": limit, "filter": "posts_and_author_threads"},
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json().get("feed", [])


@app.command()
def feed(
    name: str = typer.Argument(None, help="Agent name (default: all agents)"),
    limit: int = typer.Option(10, "--limit", help="Posts per agent"),
    config_path: str = typer.Option(None, "--config"),
):
    """Print recent Bluesky posts from one agent (or all agents)."""
    config = _config(config_path)
    targets = [config.agents[name]] if name else list(config.agents.values())

    for agent in targets:
        typer.echo(f"=== {agent.name} ({agent.handle}) ===")
        try:
            entries = _fetch_author_feed(agent.handle, limit)
        except httpx.HTTPError as e:
            typer.echo(f"  (error: {e})")
            continue
        for entry in entries:
            post = entry.get("post", {})
            record = post.get("record", {})
            text = record.get("text", "")
            when = record.get("createdAt") or post.get("indexedAt", "")
            typer.echo(f"  [{when}] {text}")


@app.command()
def talk(
    name: str = typer.Argument(..., help="Agent name"),
    prompt: str = typer.Argument(..., help="One-shot prompt for the agent"),
    config_path: str = typer.Option(None, "--config"),
):
    """Send a one-shot stateless prompt to an agent. Runs as a tick."""
    config = _config(config_path)
    sprite_id = _require_sprite_id(config, name)
    sprites = SpritesClient()
    quoted = shlex.quote(prompt)
    result = sprites.exec(
        sprite_id,
        ["bash", "-lc", f"slop-tick {quoted}"],
    )
    typer.echo(result.stdout)
    if result.stderr:
        typer.echo(result.stderr, err=True)
    if result.exit_code != 0:
        raise typer.Exit(code=result.exit_code)


# How many agents tick concurrently in `wake`. The collective shares one
# vLLM instance; capping concurrency keeps it saturated without queue thrash.
# Raise toward saturation, lower for more headroom.
WAKE_CONCURRENCY = 4


@app.command()
def wake(
    config_path: str = typer.Option(None, "--config"),
):
    """Fire a `tick` at every live agent, a few at a time.

    Driven by the `slop-wake.timer` systemd user unit on the admin box.
    Ticks run `sprite exec ... slop-tick "tick"`; concurrency is capped at
    WAKE_CONCURRENCY so the shared vLLM is saturated but not thrashed.
    Exits non-zero if any agent failed, so systemd records a red run.
    """
    config = _config(config_path)
    live = [a for a in config.agents.values() if a.live and a.sprite_id]
    if not live:
        typer.echo("no live agents to wake", err=True)
        raise typer.Exit(code=1)

    sprites = SpritesClient()

    def _tick(agent):
        start = time.monotonic()
        result = sprites.exec(
            agent.sprite_id,
            ["bash", "-lc", 'slop-tick "tick"'],
        )
        return agent, result, time.monotonic() - start

    failed = 0
    with ThreadPoolExecutor(max_workers=min(WAKE_CONCURRENCY, len(live))) as pool:
        for agent, result, elapsed in pool.map(_tick, live):
            status = "ok" if result.exit_code == 0 else f"fail({result.exit_code})"
            typer.echo(f"{agent.name:12s}  {status:12s}  {elapsed:6.1f}s")
            if result.exit_code != 0:
                failed += 1
                tail = (result.stderr or result.stdout).strip().splitlines()[-5:]
                for line in tail:
                    typer.echo(f"    {line}", err=True)
    if failed:
        raise typer.Exit(code=1)


SINCE_UNITS = {
    "min": 60,
    "mins": 60,
    "minute": 60,
    "minutes": 60,
    "hour": 3600,
    "hours": 3600,
    "day": 86400,
    "days": 86400,
    "week": 604800,
    "weeks": 604800,
}


def _parse_since(s: str | None) -> float | None:
    """`6.hours` / `1.day` → unix-timestamp cutoff. None or empty → no filter."""
    if not s:
        return None
    if "." not in s:
        raise typer.BadParameter(f"--since must be <number>.<unit>, got {s!r}")
    num_str, unit = s.split(".", 1)
    try:
        n = float(num_str)
    except ValueError as e:
        raise typer.BadParameter(f"--since: not a number: {num_str!r}") from e
    if unit not in SINCE_UNITS:
        raise typer.BadParameter(f"--since: unknown unit {unit!r} (try hours, days)")
    return time.time() - n * SINCE_UNITS[unit]


@app.command()
def usage(
    name: str = typer.Argument(None, help="Agent name (omit for all live)"),
    since: str = typer.Option(None, "--since", help="Window e.g. '6.hours', '1.day', '7.days'"),
    per_tick: bool = typer.Option(False, "--per-tick", help="One row per session, no aggregation"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON instead of a table"),
    config_path: str = typer.Option(None, "--config"),
):
    """Per-tick token usage and approximate cost across live agents.

    Fans out to each live sprite, runs `slop-usage tally <name>` in-sprite to
    read its Claude Code session transcripts, and aggregates the results.
    Costs are approximate Sonnet pricing as of 2026-05; see
    `slop_salon.tools.usage` for the constants.
    """
    config = _config(config_path)
    if name:
        if name not in config.agents:
            typer.echo(f"error: unknown agent {name!r}", err=True)
            raise typer.Exit(code=1)
        targets = [config.agents[name]]
    else:
        targets = [a for a in config.agents.values() if a.live and a.sprite_id]
    if not targets:
        typer.echo("no live agents", err=True)
        raise typer.Exit(code=1)

    cutoff = _parse_since(since)
    sprites = SpritesClient()

    def _fetch(agent):
        cmd = f"slop-usage tally {shlex.quote(agent.name)}"
        result = sprites.exec(agent.sprite_id, ["bash", "-lc", cmd])
        if result.exit_code != 0:
            return agent, [], (result.stderr or result.stdout or "").strip()
        rows = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if cutoff is not None:
            rows = [r for r in rows if r.get("mtime", 0) >= cutoff]
        return agent, rows, None

    with ThreadPoolExecutor(max_workers=len(targets)) as pool:
        results = list(pool.map(_fetch, targets))

    if per_tick:
        for agent, rows, err in results:
            if err:
                typer.echo(f"{agent.name}: ERROR {err[:80]}", err=True)
                continue
            for r in rows:
                if json_out:
                    typer.echo(json.dumps(r))
                else:
                    typer.echo(
                        f"{agent.name:<8} {r['session']:<10} turns={r['turns']:<3} "
                        f"in_new={r['in_new']:>6} cache_cr={r['cache_create']:>7} "
                        f"cache_rd={r['cache_read']:>8} out={r['output']:>6} "
                        f"${r['cost_usd']:.3f}"
                    )
        return

    if json_out:
        out = []
        for agent, rows, err in results:
            non_empty = [r for r in rows if r["turns"] > 0]
            entry = {
                "agent": agent.name,
                "ticks": len(non_empty),
                "empty": len(rows) - len(non_empty),
            }
            if err:
                entry["error"] = err
            elif non_empty:
                costs = sorted(r["cost_usd"] for r in non_empty)
                entry.update(
                    {
                        "median_cost_usd": round(median(costs), 4),
                        "mean_cost_usd": round(mean(costs), 4),
                        "max_cost_usd": round(max(costs), 4),
                        "total_cost_usd": round(sum(costs), 2),
                        "median_turns": int(median(r["turns"] for r in non_empty)),
                        "median_output_tokens": int(median(r["output"] for r in non_empty)),
                    }
                )
            out.append(entry)
        typer.echo(json.dumps(out, indent=2))
        return

    typer.echo(
        f"{'agent':<8}{'ticks':>6}{'empty':>6}  {'turns':>5}  {'output':>8}  "
        f"{'med $/tick':>12}  {'p95 $/tick':>12}  {'total $':>10}"
    )
    typer.echo("-" * 76)
    grand_total = 0.0
    for agent, rows, err in results:
        if err:
            typer.echo(f"{agent.name:<8}  ERROR: {err[:60]}")
            continue
        non_empty = [r for r in rows if r["turns"] > 0]
        empty = len(rows) - len(non_empty)
        if not non_empty:
            typer.echo(f"{agent.name:<8}{0:>6}{empty:>6}  (no ticks in window)")
            continue
        costs = sorted(r["cost_usd"] for r in non_empty)
        med = costs[len(costs) // 2]
        p95 = costs[int(0.95 * (len(costs) - 1))]
        total = sum(costs)
        grand_total += total
        med_turns = sorted(r["turns"] for r in non_empty)[len(non_empty) // 2]
        med_out = sorted(r["output"] for r in non_empty)[len(non_empty) // 2]
        typer.echo(
            f"{agent.name:<8}{len(non_empty):>6}{empty:>6}  {med_turns:>5}  "
            f"{med_out:>8}  ${med:>10.3f}  ${p95:>10.3f}  ${total:>8.2f}"
        )
    typer.echo(
        f"{'total':<8}{'':>6}{'':>6}  {'':>5}  {'':>8}  {'':>12}  {'':>12}  ${grand_total:>8.2f}"
    )


DRIFT_DEFAULT_FILES = ("SOUL.md", "CLAUDE.md", "slop-tick")


def _fetch_live_files(repo: str, files: list[str]) -> dict[str, str | None]:
    """Shallow-clone `repo` and return {filename: content or None if missing}."""
    with tempfile.TemporaryDirectory() as td:
        clone_dir = Path(td) / "repo"
        subprocess.run(
            ["gh", "repo", "clone", repo, str(clone_dir), "--", "--depth=1"],
            check=True,
            capture_output=True,
        )
        return {f: (clone_dir / f).read_text() if (clone_dir / f).exists() else None for f in files}


@app.command()
def drift(
    name: str = typer.Argument(None, help="Agent name (omit to scan all)"),
    file: list[str] = typer.Option(
        None, "--file", "-f", help=f"Files to check (default: {', '.join(DRIFT_DEFAULT_FILES)})"
    ),
    templates_dir: str = typer.Option("templates", "--templates"),
    soul_path: str = typer.Option("SOUL.md", "--soul"),
    config_path: str = typer.Option(None, "--config"),
):
    """Diff live agent repos against the canonical templates.

    Use to spot SOUL.md tampering (should always be clean) and to inspect
    how each agent has edited its own CLAUDE.md (drift is expected there).
    Also flags template files missing from a live repo --- e.g. an agent
    provisioned before a new template file was added.
    """
    config = _config(config_path)
    if name:
        if name not in config.agents:
            typer.echo(f"error: unknown agent {name!r}", err=True)
            raise typer.Exit(code=1)
        targets = [config.agents[name]]
    else:
        targets = list(config.agents.values())

    files = list(file) if file else list(DRIFT_DEFAULT_FILES)

    for i, agent in enumerate(targets):
        if i:
            typer.echo("")
        siblings = [(s, config.agents[s].handle) for s in agent.siblings if s in config.agents]
        expected = _build_template_files(
            Path(templates_dir),
            Path(soul_path),
            agent.name,
            agent.handle,
            siblings,
        )
        try:
            live = _fetch_live_files(agent.github_repo, files)
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr.decode().strip() if e.stderr else "").splitlines()
            tail = stderr[-1] if stderr else f"exit {e.returncode}"
            typer.echo(f"{agent.name}\n  could not fetch {agent.github_repo}: {tail}")
            continue
        typer.echo(agent.name)
        for f in files:
            exp = expected.get(f)
            got = live.get(f)
            if exp is None:
                typer.echo(f"  {f:14s}  no template")
                continue
            if got is None:
                typer.echo(f"  {f:14s}  MISSING from live repo")
                continue
            if exp == got:
                typer.echo(f"  {f:14s}  clean")
                continue
            diff_lines = list(
                difflib.unified_diff(
                    exp.splitlines(keepends=True),
                    got.splitlines(keepends=True),
                    fromfile=f"template/{f}",
                    tofile=f"{agent.name}/{f}",
                )
            )
            added = sum(1 for ln in diff_lines if ln.startswith("+") and not ln.startswith("+++"))
            removed = sum(1 for ln in diff_lines if ln.startswith("-") and not ln.startswith("---"))
            typer.echo(f"  {f:14s}  drift (+{added}/-{removed})")
            for line in diff_lines:
                typer.echo(f"    {line.rstrip()}")


@app.command(name="install-hooks")
def install_hooks(
    name: str = typer.Argument(..., help="Agent name (use 'all' for every live agent)"),
    config_path: str = typer.Option(None, "--config"),
):
    """Push the ambient-recall hook + Claude Code settings to a live sprite.

    Idempotent retrofit for sprites provisioned before the hook existed.
    Also runs `uv tool upgrade slop-salon` so `slop-recall` is on PATH.
    `provision_agent` runs the same install step for new agents.
    """
    config = _config(config_path)
    if name == "all":
        targets = [a for a in config.agents.values() if a.live and a.sprite_id]
        if not targets:
            typer.echo("no live agents", err=True)
            raise typer.Exit(code=1)
    else:
        _require_sprite_id(config, name)
        targets = [config.agents[name]]

    sprites = SpritesClient()
    # --reinstall pulls the latest commit on git+https sources without
    # caring about the package version, which we don't bump per-change.
    upgrade_cmd = f"~/.local/bin/uv tool install --reinstall {SLOP_SALON_REPO}"
    hook_cmd = _build_install_ambient_hook_cmd()

    failed = 0
    for agent in targets:
        typer.echo(f"{agent.name:12s}  reinstalling slop-salon...")
        result = sprites.exec(agent.sprite_id, ["bash", "-lc", upgrade_cmd])
        if result.exit_code != 0:
            typer.echo(f"  upgrade failed: {result.stderr or result.stdout}", err=True)
            failed += 1
            continue
        typer.echo(f"{agent.name:12s}  installing hook...")
        result = sprites.exec(agent.sprite_id, ["bash", "-lc", hook_cmd])
        if result.exit_code != 0:
            typer.echo(f"  hook install failed: {result.stderr or result.stdout}", err=True)
            failed += 1
            continue
        typer.echo(f"{agent.name:12s}  ok")
    if failed:
        raise typer.Exit(code=1)


@app.command()
def new(
    name: str = typer.Argument(..., help="New agent name (must already be in slop_salon.toml)"),
    yes_dns: bool = typer.Option(
        False, "--yes-dns", help="Skip the manual DNS confirmation prompt"
    ),
    config_path: str = typer.Option(None, "--config"),
):
    """Provision a new agent end-to-end."""
    provision_agent(
        name,
        config_path=config_path or "slop_salon.toml",
        skip_dns_confirm=yes_dns,
    )


SIBLINGS_HEADER_RE = re.compile(r"^## (\S+)\s*$", re.MULTILINE)


@app.command(name="sync-siblings")
def sync_siblings(
    name: str = typer.Argument(None, help="Agent name (omit to sync all live agents)"),
    config_path: str = typer.Option(None, "--config"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Report missing entries but do not commit/push"
    ),
):
    """Backfill missing sibling entries in each live agent's SIBLINGS.md.

    Preserves existing entries (and any notes the agent has accumulated);
    appends fresh stubs for siblings listed in slop_salon.toml but not yet
    present as `## <name>` headers. Idempotent.
    """
    config = _config(config_path)
    if name:
        if name not in config.agents:
            typer.echo(f"error: unknown agent {name!r}", err=True)
            raise typer.Exit(code=1)
        targets = [config.agents[name]]
    else:
        targets = [a for a in config.agents.values() if a.live]
    if not targets:
        typer.echo("no live agents to sync", err=True)
        raise typer.Exit(code=1)

    gh_token = resolve_secrets(targets[0].name, list(config.agents.keys())).get("GH_TOKEN")
    if not gh_token:
        typer.echo("error: SLOP_GH_TOKEN missing from env", err=True)
        raise typer.Exit(code=1)
    push_env = {**os.environ, "GH_TOKEN": gh_token}

    for agent in targets:
        sibling_handles = {s: config.agents[s].handle for s in agent.siblings if s in config.agents}
        with tempfile.TemporaryDirectory() as tmp:
            clone_dir = Path(tmp) / "repo"
            subprocess.run(
                ["gh", "repo", "clone", agent.github_repo, str(clone_dir)],
                check=True,
                capture_output=True,
                env=push_env,
            )
            siblings_path = clone_dir / "SIBLINGS.md"
            current = siblings_path.read_text() if siblings_path.exists() else ""
            present = set(SIBLINGS_HEADER_RE.findall(current))
            missing = [s for s in agent.siblings if s in sibling_handles and s not in present]

            if not missing:
                typer.echo(f"{agent.name:12s}  clean")
                continue

            new_blocks = "\n\n".join(_render_sibling_block(s, sibling_handles[s]) for s in missing)
            if current.strip():
                new_content = current.rstrip() + "\n\n" + new_blocks + "\n"
            else:
                new_content = (
                    "# Siblings\n\n"
                    "The other artists in the Slop Salon. "
                    "Your accumulated observations go below.\n\n" + new_blocks + "\n"
                )

            if dry_run:
                typer.echo(f"{agent.name:12s}  would add: {', '.join(missing)}")
                continue

            siblings_path.write_text(new_content)
            subprocess.run(["git", "add", "SIBLINGS.md"], cwd=clone_dir, check=True)
            subprocess.run(
                ["git", "commit", "-m", "Sync siblings from slop_salon.toml"],
                cwd=clone_dir,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "push"],
                cwd=clone_dir,
                check=True,
                capture_output=True,
                env=push_env,
            )
            typer.echo(f"{agent.name:12s}  added: {', '.join(missing)}")
