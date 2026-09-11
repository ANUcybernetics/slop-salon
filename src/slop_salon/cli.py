"""Admin `slop` CLI.

status      one line per agent: handle, sprite state
feed        recent Bluesky posts (across or per agent)
logs        recent tick transcripts from a sprite
diff        repo changes since a duration
drift       template vs live-repo divergence per agent
talk        one-shot prompt to an agent, run as a tick
wake        a tick at every live agent (the timer's job)
wake-check  dead-man check on the pipeline
cadence     show or change how often the fleet ticks
policy      (re)apply the egress allowlist to sprites
new         provision a new agent
recreate    destroy and rebuild an agent's sprite from its repo
reset       season reset: tag, orphan templates, recreate, Bluesky hygiene
"""

from __future__ import annotations

import datetime as dt
import difflib
import json
import shlex
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
import typer

from . import cadence as cadence_mod
from . import wake as wake_mod
from . import watchdog
from .config import load_config
from .provision import EGRESS_RULES, build_template_files, provision_agent
from .recreate import recreate as recreate_agent
from .reset import SEASON
from .reset import reset as reset_agent
from .sprites import SpritesClient
from .tick import tick_env

app = typer.Typer(add_completion=False, help="Slop Salon admin CLI.")

CONFIG_OPTION = typer.Option(None, "--config", help="Path to slop_salon.toml")


@app.callback()
def main() -> None:
    """Slop Salon admin CLI."""


def _config(path: str | None = None):
    return load_config(path or "slop_salon.toml")


def _agent(config, name: str):
    agent = config.agents.get(name)
    if agent is None:
        typer.echo(f"error: unknown agent {name!r}", err=True)
        raise typer.Exit(code=1)
    if not agent.sprite_id:
        typer.echo(f"error: agent {name!r} has no sprite_id (not provisioned?)", err=True)
        raise typer.Exit(code=1)
    return agent


def _targets(config, name: str | None):
    """One agent, or every live one for `all`/None."""
    if name in (None, "all"):
        targets = config.live_agents()
        if not targets:
            typer.echo("no live agents", err=True)
            raise typer.Exit(code=1)
        return targets
    return [_agent(config, name)]


@app.command()
def status(config_path: str = CONFIG_OPTION):
    """Print one line per agent: name, handle, salon, soul, sprite state."""
    config = _config(config_path)
    sprites = SpritesClient()
    for name, agent in config.agents.items():
        if agent.sprite_id:
            try:
                sprite_state = sprites.get_status(agent.sprite_id)
            except Exception as e:  # noqa: BLE001 --- one dead sprite must not abort the sweep
                sprite_state = f"error: {e}"
        else:
            sprite_state = "not provisioned"
        typer.echo(
            f"{name:10s} {agent.handle:26s} {agent.salon:11s} {agent.soul:8s} {sprite_state}"
        )


# --- Reading ---

_SLOPLOG_DELIM = "<<<SLOPLOG "


@app.command()
def logs(
    name: str = typer.Argument(..., help="Agent name"),
    sessions: int = typer.Option(1, "--sessions", "-n", help="Recent tick sessions, newest first"),
    config_path: str = CONFIG_OPTION,
):
    """Print recent claude tick transcripts from the agent's sprite, rendered as turns."""
    config = _config(config_path)
    agent = _agent(config, name)
    # One JSONL transcript per session under ~/.claude/projects/<munged cwd>/.
    remote = (
        f"ls -t ~/.claude/projects/*slop-salon-{shlex.quote(name)}/*.jsonl 2>/dev/null "
        f"| head -{max(1, sessions)} | while read -r f; do "
        f'echo "{_SLOPLOG_DELIM}$(basename "$f") '
        '$(date -u -r "$f" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)>>>"; '
        'cat "$f"; done'
    )
    result = SpritesClient().exec(agent.sprite_id, ["bash", "-lc", remote])
    if result.stderr.strip():
        typer.echo(result.stderr, err=True)
    rendered = _render_transcripts(result.stdout)
    typer.echo(rendered if rendered.strip() else "(no transcripts found)")


def _render_transcripts(stream: str) -> str:
    sessions: list[tuple[str, list[str]]] = []
    header: str | None = None
    body: list[str] = []
    for line in stream.splitlines():
        if line.startswith(_SLOPLOG_DELIM):
            if header is not None:
                sessions.append((header, body))
            header = line[len(_SLOPLOG_DELIM) :].rstrip(">").strip()
            body = []
        elif header is not None:
            body.append(line)
    if header is not None:
        sessions.append((header, body))
    return "\n\n".join(_render_session(h, b) for h, b in sessions)


def _render_session(header: str, raw_lines: list[str]) -> str:
    parts = header.split()
    session_id = parts[0].removesuffix(".jsonl")[:8] if parts else "?"
    mtime = parts[1] if len(parts) > 1 else ""
    rows: list[str] = []
    for raw in raw_lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        rows.extend(_render_entry(obj))
    title = f"-- tick {session_id}" + (f" · {mtime}" if mtime else "") + " --"
    return "\n".join([title, *rows]) if rows else title


def _render_entry(obj: dict) -> list[str]:
    typ = obj.get("type")
    ts = _short_ts(obj.get("timestamp", ""))
    content = (obj.get("message") or {}).get("content")
    if typ == "user":
        if isinstance(content, str):
            text = _oneline(content)
            return [f"{ts}  user       {_truncate(text, 500)}"] if text else []
        return [
            f"{ts}    <- {_truncate(_oneline(_block_text(block)), 300)}"
            for block in (content if isinstance(content, list) else [])
            if isinstance(block, dict) and block.get("type") == "tool_result"
        ]
    if typ == "assistant":
        rows = []
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict):
                continue
            bt = block.get("type")
            if bt == "thinking":
                think = _oneline(block.get("thinking", ""))
                if think:
                    rows.append(f"{ts}    ~  {_truncate(think, 240)}")
            elif bt == "text":
                text = block.get("text", "").strip()
                if text:
                    rows.append(f"{ts}  assistant  {_truncate(text, 800)}")
            elif bt == "tool_use":
                args = _oneline(_compact(block.get("input")))
                rows.append(f"{ts}    -> {block.get('name', '?')}({_truncate(args, 200)})")
        if not rows and isinstance(content, str) and content.strip():
            rows.append(f"{ts}  assistant  {_truncate(content.strip(), 800)}")
        return rows
    return []


def _block_text(block: dict) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def _compact(value) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    except TypeError, ValueError:
        return str(value)


def _oneline(text: str) -> str:
    return " ".join(text.split())


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _short_ts(iso: str) -> str:
    return iso.split("T", 1)[1][:8] if "T" in iso else " " * 8


@app.command()
def diff(
    name: str = typer.Argument(..., help="Agent name"),
    since: str = typer.Option("1.day", "--since", help="Git revspec or duration ('2.hours')"),
    config_path: str = CONFIG_OPTION,
):
    """Show recent repo changes from the agent's sprite."""
    config = _config(config_path)
    agent = _agent(config, name)
    result = SpritesClient().exec(
        agent.sprite_id,
        [
            "bash",
            "-lc",
            f"cd ~/slop-salon-{shlex.quote(name)} && "
            f"git log --since={shlex.quote(since)} --stat -p",
        ],
    )
    typer.echo(result.stdout)
    if result.stderr:
        typer.echo(result.stderr, err=True)


APPVIEW = "https://public.api.bsky.app"


@app.command()
def feed(
    name: str = typer.Argument(None, help="Agent name (default: all agents)"),
    limit: int = typer.Option(10, "--limit", help="Posts per agent"),
    config_path: str = CONFIG_OPTION,
):
    """Print recent Bluesky posts from one agent (or all agents)."""
    config = _config(config_path)
    targets = [config.agents[name]] if name else list(config.agents.values())
    for agent in targets:
        typer.echo(f"=== {agent.name} ({agent.handle}) ===")
        try:
            response = httpx.get(
                f"{APPVIEW}/xrpc/app.bsky.feed.getAuthorFeed",
                params={
                    "actor": agent.handle,
                    "limit": limit,
                    "filter": "posts_and_author_threads",
                },
                timeout=10.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            typer.echo(f"  (error: {e})")
            continue
        for entry in response.json().get("feed", []):
            post = entry.get("post", {})
            record = post.get("record", {})
            when = record.get("createdAt") or post.get("indexedAt", "")
            typer.echo(f"  [{when}] {record.get('text', '')}")


# --- Ticking ---


@app.command()
def talk(
    name: str = typer.Argument(..., help="Agent name"),
    prompt: str = typer.Argument(..., help="One-shot prompt for the agent"),
    config_path: str = CONFIG_OPTION,
):
    """Send a one-shot prompt to an agent. Runs as a tick, blocking until it ends."""
    config = _config(config_path)
    agent = _agent(config, name)
    result = SpritesClient().exec(
        agent.sprite_id,
        ["bash", "-lc", f"slop-tick {shlex.quote(prompt)}"],
        env=tick_env(config, agent),
    )
    typer.echo(result.stdout)
    if result.stderr:
        typer.echo(result.stderr, err=True)
    if result.exit_code != 0:
        raise typer.Exit(code=result.exit_code)


@app.command()
def wake(
    only: list[str] = typer.Option(None, "--only", help="Tick just these agents (repeatable)"),
    config_path: str = CONFIG_OPTION,
):
    """Fire a `tick` at every live agent, a few at a time. Non-zero if any failed.

    Driven by `slop-wake.timer` on the admin box. A wedged sprite (the
    connection i/o-timeout signature) is retried once, and recreated after a
    second consecutive wedged wake unless three or more wedge together.
    """
    config = _config(config_path)
    report = wake_mod.run(
        config,
        SpritesClient(),
        only=list(only) if only else None,
        recreate_fn=lambda n: recreate_agent(n, config_path=config_path or "slop_salon.toml"),
        echo=typer.echo,
    )
    try:
        wake_mod.write_stamp(report.statuses, now=dt.datetime.now(dt.UTC))
    except OSError as exc:
        typer.echo(f"could not write wake stamp (ignored): {exc!r}", err=True)
    if not report.ok:
        raise typer.Exit(code=1)


def _timer_stopped_for(timer: str) -> float | None:
    """Seconds the timer has been inactive, or None while armed. Read off
    systemd's monotonic clock, the same one `time.monotonic()` reads."""
    completed = subprocess.run(
        [
            "systemctl",
            "--user",
            "show",
            timer,
            "-p",
            "ActiveState",
            "-p",
            "InactiveEnterTimestampMonotonic",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    shown = dict(line.split("=", 1) for line in completed.stdout.splitlines() if "=" in line)
    if shown.get("ActiveState") == "active":
        return None
    try:
        since_boot = int(shown.get("InactiveEnterTimestampMonotonic", 0)) / 1_000_000
    except ValueError:
        since_boot = 0.0
    return max(0.0, time.monotonic() - since_boot)


def _format_duration(seconds: float) -> str:
    return f"{seconds / 60:.0f}min" if seconds < 3600 else f"{seconds / 3600:.1f}h"


@app.command(name="wake-check")
def wake_check(
    max_age: str = typer.Option(
        None, "--max-age", help="Staleness limit, e.g. '3.hours' (default: from the cadence)"
    ),
    timer: str = typer.Option("slop-wake.timer", "--timer", help="Wake timer unit"),
):
    """Dead-man check on the tick pipeline. Non-zero if anything is wrong.

    Run hourly by `slop-wake-watchdog.timer`, whose OnFailure= files an oncall
    todo. Both limits derive from the timer's cadence (see `slop_salon.cadence`).
    """
    limit = _parse_duration(max_age) if max_age else cadence_mod.current_max_age(timer)
    grace = cadence_mod.current_grace(timer)
    stopped_for = _timer_stopped_for(timer)
    found = watchdog.problems(
        stamp=watchdog.read_stamp(),
        now=dt.datetime.now(dt.UTC),
        max_age=limit,
        timer_stopped_for=stopped_for,
        timer_grace=grace,
        timer_name=timer,
    )
    if not found:
        armed = (
            f"{timer} armed"
            if stopped_for is None
            else f"{timer} stopped {_format_duration(stopped_for)} ago, inside the "
            f"{_format_duration(grace)} a pause is given"
        )
        typer.echo(f"ok: {armed}, wake stamp fresh (<{_format_duration(limit)})")
        return
    for problem in found:
        typer.echo(f"WAKE-CHECK: {problem}", err=True)
    raise typer.Exit(code=1)


_DURATION_UNITS = {
    "min": 60,
    "mins": 60,
    "minute": 60,
    "minutes": 60,
    "hour": 3600,
    "hours": 3600,
    "day": 86400,
    "days": 86400,
}


def _parse_duration(s: str) -> float:
    """`90.mins` / `3.hours` -> seconds."""
    if "." not in s:
        raise typer.BadParameter(f"duration must be <number>.<unit>, got {s!r}")
    num_str, unit = s.split(".", 1)
    try:
        n = float(num_str)
    except ValueError as e:
        raise typer.BadParameter(f"duration: not a number: {num_str!r}") from e
    if unit not in _DURATION_UNITS:
        raise typer.BadParameter(f"duration: unknown unit {unit!r} (try mins, hours)")
    return n * _DURATION_UNITS[unit]


@app.command()
def cadence(
    spec: str = typer.Argument(None, help="e.g. '6h', '30m', or a raw OnCalendar"),
    timer: str = typer.Option("slop-wake.timer", "--timer"),
):
    """Show or change how often the fleet ticks. Takes effect immediately.

    Cadence is the only lever with real leverage over cost: a tick's price is
    dominated by its fixed prompt floor, so ticks are far easier to make rarer
    than cheaper. It also sets how much of the salon an agent sees between
    ticks, and so how conversational the work feels.
    """
    dropin = Path.home() / ".config/systemd/user" / cadence_mod.DROPIN_DIR / cadence_mod.DROPIN_NAME
    if spec:
        try:
            oncalendar = cadence_mod.spec_to_oncalendar(spec)
            analysis = cadence_mod.analyse(oncalendar)
        except ValueError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        dropin.parent.mkdir(parents=True, exist_ok=True)
        dropin.write_text(cadence_mod.render_dropin(oncalendar))
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        typer.echo(f"cadence set: {oncalendar}\n  {dropin}")
        # Never start a stopped timer from here: the fleet is paused on purpose
        # at times, and a config command that resumes ticking is a surprise.
        if _timer_stopped_for(timer) is None:
            subprocess.run(["systemctl", "--user", "restart", timer], check=True)
        else:
            typer.echo(
                f"  note: {timer} is not running; start it with `systemctl --user start {timer}`"
            )
    else:
        oncalendar = cadence_mod.active_oncalendar(timer)
        if not oncalendar:
            typer.echo(f"error: could not read {timer}", err=True)
            raise typer.Exit(code=1)
        analysis = cadence_mod.analyse(oncalendar)
        typer.echo(f"cadence: {oncalendar}")
    gap = cadence_mod.longest_gap(cadence_mod.parse_elapses(analysis))
    if gap:
        typer.echo(f"  every {_format_duration(gap)} ({int(86400 / gap)} ticks/agent/day)")
        typer.echo(
            f"  dead-man check now allows "
            f"{_format_duration(cadence_mod.max_age_for(gap))} of silence"
        )
    for line in analysis.splitlines():
        if "Next elapse" in line:
            typer.echo(f"  {line.strip()}")


# --- Sprites and repos ---


@app.command()
def policy(
    name: str = typer.Argument(None, help="Agent name; omit or 'all' for every live agent"),
    config_path: str = CONFIG_OPTION,
):
    """(Re)apply the DNS egress allowlist to sprites. Provisioning and recreate
    already do this; run it after editing `EGRESS_RULES` for a live fleet."""
    config = _config(config_path)
    sprites = SpritesClient()
    for agent in _targets(config, name):
        sprites.set_network_policy(agent.sprite_id, EGRESS_RULES)
        typer.echo(f"{agent.name:12s}  policy applied ({len(EGRESS_RULES)} rules)")


DRIFT_DEFAULT_FILES = ("SOUL.md", "CLAUDE.md", "slop-tick", "setup.sh", ".gitignore")
DRIFT_FILES_HELP = f"Files to check (default: {', '.join(DRIFT_DEFAULT_FILES)})"


def _fetch_live_files(repo: str, files: list[str]) -> dict[str, str | None]:
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
    file: list[str] = typer.Option(None, "--file", "-f", help=DRIFT_FILES_HELP),
    templates_dir: str = typer.Option("templates", "--templates"),
    souls_dir: str = typer.Option("souls", "--souls"),
    config_path: str = CONFIG_OPTION,
):
    """Diff live agent repos against the templates. SOUL.md drift is a bug;
    CLAUDE.md and setup.sh drift is expected, and the point."""
    config = _config(config_path)
    targets = [config.agents[name]] if name in config.agents else list(config.agents.values())
    if name and name not in config.agents:
        typer.echo(f"error: unknown agent {name!r}", err=True)
        raise typer.Exit(code=1)
    files = list(file) if file else list(DRIFT_DEFAULT_FILES)
    for i, agent in enumerate(targets):
        if i:
            typer.echo("")
        expected = build_template_files(config, agent, templates_dir, souls_dir)
        try:
            live = _fetch_live_files(agent.github_repo, files)
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr.decode().strip() if e.stderr else "").splitlines()
            typer.echo(
                f"{agent.name}\n  could not fetch {agent.github_repo}: "
                f"{stderr[-1] if stderr else e.returncode}"
            )
            continue
        typer.echo(agent.name)
        for f in files:
            exp, got = expected.get(f), live.get(f)
            if exp is None:
                typer.echo(f"  {f:14s}  no template")
            elif got is None:
                typer.echo(f"  {f:14s}  MISSING from live repo")
            elif exp == got:
                typer.echo(f"  {f:14s}  clean")
            else:
                diff_lines = list(
                    difflib.unified_diff(
                        exp.splitlines(keepends=True),
                        got.splitlines(keepends=True),
                        fromfile=f"template/{f}",
                        tofile=f"{agent.name}/{f}",
                    )
                )
                added = sum(
                    1 for ln in diff_lines if ln.startswith("+") and not ln.startswith("+++")
                )
                removed = sum(
                    1 for ln in diff_lines if ln.startswith("-") and not ln.startswith("---")
                )
                typer.echo(f"  {f:14s}  drift (+{added}/-{removed})")
                for line in diff_lines:
                    typer.echo(f"    {line.rstrip()}")


@app.command()
def new(
    name: str = typer.Argument(..., help="New agent name (must already be in slop_salon.toml)"),
    yes_dns: bool = typer.Option(
        False, "--yes-dns", help="Skip the manual DNS confirmation prompt"
    ),
    config_path: str = CONFIG_OPTION,
):
    """Provision a new agent end-to-end."""
    provision_agent(name, config_path=config_path or "slop_salon.toml", skip_dns_confirm=yes_dns)


@app.command()
def recreate(
    name: str = typer.Argument(..., help="Agent whose sprite to destroy and rebuild"),
    config_path: str = CONFIG_OPTION,
):
    """Destroy and rebuild an agent's sprite from its repo (the wedge remedy)."""
    recreate_agent(name, config_path=config_path or "slop_salon.toml")


@app.command()
def reset(
    name: str = typer.Argument(..., help="Agent to reset (must have a sprite and a repo)"),
    tag: str = typer.Option(f"season-{SEASON - 1}", "--tag", help="Tag to leave on the old head"),
    skip_repo: bool = typer.Option(
        False, "--skip-repo", help="Retry without the tag + orphan push"
    ),
    skip_sprite: bool = typer.Option(False, "--skip-sprite", help="Leave the sprite alone"),
    skip_bluesky: bool = typer.Option(
        False, "--skip-bluesky", help="Leave the Bluesky profile alone"
    ),
    marker: bool = typer.Option(True, "--marker/--no-marker", help="Post and pin a season marker"),
    discard_unpushed: bool = typer.Option(
        False, "--discard-unpushed", help="Reset even if the sprite holds commits not on GitHub"
    ),
    config_path: str = CONFIG_OPTION,
):
    """Reset an agent to a fresh season start (see reset.py). Stop the wake
    timer first: the pre-flight refuses a sprite mid-tick."""
    reset_agent(
        name,
        config_path=config_path or "slop_salon.toml",
        tag=tag,
        skip_repo=skip_repo,
        skip_sprite=skip_sprite,
        skip_bluesky=skip_bluesky,
        marker=marker,
        discard_unpushed=discard_unpushed,
    )
