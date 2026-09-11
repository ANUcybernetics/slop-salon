"""One wake: a tick at every live agent, a few at a time.

Driven by `slop-wake.timer` on the admin box. Firings never overlap (a 2h tick
cap against a 6h cadence), so there is no global slot bookkeeping and no
in-sprite lock; the only state carried between wakes is a per-agent count of
consecutive wedges, kept so a second wedge in a row triggers a recreate. A
wedge is a tick whose sprite never reported for duty, twice running --- see
`never_started`.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .config import Agent, Config
from .sprites import ExecResult, SpriteExecutor
from .tick import SESSION_MARKER, tick_command, tick_env, tick_output

WAKE_CONCURRENCY = 4
# A wedge this many wakes running is recreated; fewer is a blip.
WEDGE_RECREATE_AFTER = 2
# This many wedged in one wake is a platform incident: recreating will not help
# and may make it worse, so hold off and say so.
PLATFORM_INCIDENT_THRESHOLD = 3

# slop-tick prints these when `claude -p` fails but the tick still exits 0 so it
# can commit partial work; unsurfaced, an agent whose every tick errors reads
# as healthy.
_CLAUDE_ERROR_MARKERS = ("slop-tick: claude exited", "slop-tick: claude exceeded")
_ERROR_LINE = re.compile(r"error|fatal|rejected|exceeds|exceeded|traceback|exited", re.IGNORECASE)


def never_started(result: ExecResult) -> bool:
    """The exec failed without the sprite ever reporting for duty.

    Asked positively, of `tick_command`'s marker, rather than by matching the
    platform's error text: the strings change (an unreachable sprite has
    answered "failed to connect", "i/o timeout" and "connection closed" in turn)
    but the marker's absence means the same thing every time, and means it for
    an error nobody has seen yet.
    """
    return result.exit_code != 0 and SESSION_MARKER not in result.stdout


def claude_failed(result: ExecResult) -> bool:
    if result.exit_code != 0:
        return False
    blob = f"{result.stderr}\n{result.stdout}".lower()
    return any(marker in blob for marker in _CLAUDE_ERROR_MARKERS)


def classify(result: ExecResult) -> str:
    """`ok`, `claude-err`, `wedge`, or `fail(<exit code>)`.

    Read the result of a *finished* `tick_once`, retry included: a sprite that
    never started twice running is wedged, where one that started on the retry
    was only slow to wake.
    """
    if result.exit_code == 0:
        return "claude-err" if claude_failed(result) else "ok"
    return "wedge" if never_started(result) else f"fail({result.exit_code})"


def failure_tail(result: ExecResult, limit: int = 5) -> list[str]:
    """The lines worth printing under a failed tick: both streams, tagged, and
    within each the lines that look like errors ahead of the last few. `claude`
    reports on stdout while git writes progress to stderr, and a tick that dies
    mid-run still commits, so a plain tail shows the commit summary and buries
    the reason claude died."""
    lines: list[str] = []
    for label, blob in (("err", result.stderr), ("out", tick_output(result.stdout))):
        stream = (blob or "").strip().splitlines()
        if not stream:
            continue
        hits = [line for line in stream if _ERROR_LINE.search(line)]
        lines.extend(f"[{label}] {line}" for line in (hits or stream)[-limit:])
    return lines


def wedge_state_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "slop" / "wedges.json"


def load_wedges(path: Path) -> dict[str, int]:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError, json.JSONDecodeError:
        return {}
    return {k: int(v) for k, v in data.items()} if isinstance(data, dict) else {}


def save_wedges(path: Path, state: dict[str, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
    tmp.replace(path)


def update_wedges(state: dict[str, int], statuses: dict[str, str]) -> tuple[list[str], bool]:
    """Advance the consecutive-wedge counters for this wake's `statuses`.

    Returns the agents due a recreate (counter at the threshold, then reset to
    zero so a recreate that does not stick waits another full threshold), and
    whether this wake looks like a platform incident, in which case nobody is
    due one however long they have been wedged.
    """
    wedged = sorted(name for name, status in statuses.items() if status == "wedge")
    for name in statuses:
        state[name] = state.get(name, 0) + 1 if name in wedged else 0
    if len(wedged) >= PLATFORM_INCIDENT_THRESHOLD:
        return [], True
    due = [name for name in wedged if state[name] >= WEDGE_RECREATE_AFTER]
    for name in due:
        state[name] = 0
    return due, False


@dataclass
class WakeReport:
    statuses: dict[str, str] = field(default_factory=dict)
    failed: list[str] = field(default_factory=list)
    recreated: list[str] = field(default_factory=list)
    platform_incident: bool = False

    @property
    def ok(self) -> bool:
        return not self.failed


def tick_once(
    sprites: SpriteExecutor, agent: Agent, env: dict[str, str]
) -> tuple[ExecResult, bool]:
    """Run one `slop-tick "tick"`, retrying once if the sprite never started.

    Resuming a cold sprite takes ~30s and the platform sometimes drops the
    connection while it does, so the second connect usually lands on a sprite
    that is now awake. Retrying is safe only because the tick provably did not
    run; a tick that started and then failed is left alone, wedged or not,
    since its `claude` may still be running in the sprite. Returns
    (result, retried).
    """
    cmd = tick_command("tick")
    result = sprites.exec(agent.sprite_id, cmd, env=env)
    if not never_started(result):
        return result, False
    return sprites.exec(agent.sprite_id, cmd, env=env), True


def run(
    config: Config,
    sprites: SpriteExecutor,
    *,
    only: list[str] | None = None,
    recreate_fn: Callable[[str], None],
    echo: Callable[[str], None],
    state_path: Path | None = None,
) -> WakeReport:
    agents = config.live_agents()
    if only:
        agents = [a for a in agents if a.name in only]
    report = WakeReport()
    if not agents:
        echo("no live agents to wake")
        return report

    # Assemble every environment first: a missing secret fails the wake before
    # any sprite is touched.
    envs = {a.name: tick_env(config, a) for a in agents}

    def _tick(agent: Agent) -> tuple[Agent, ExecResult, float, bool]:
        start = time.monotonic()
        result, retried = tick_once(sprites, agent, envs[agent.name])
        return agent, result, time.monotonic() - start, retried

    with ThreadPoolExecutor(max_workers=min(WAKE_CONCURRENCY, len(agents))) as pool:
        for agent, result, elapsed, retried in pool.map(_tick, agents):
            status = classify(result)
            report.statuses[agent.name] = status
            line = f"{agent.name:12s}  {status:12s}  {elapsed:6.1f}s"
            if retried:
                line += "  (retried: no session)"
            echo(line)
            if status != "ok":
                report.failed.append(agent.name)
                for tail in failure_tail(result):
                    echo(f"    {tail}")

    path = state_path or wedge_state_path()
    state = load_wedges(path)
    due, report.platform_incident = update_wedges(state, report.statuses)
    save_wedges(path, state)
    if report.platform_incident:
        echo(
            f"PLATFORM INCIDENT: {sum(s == 'wedge' for s in report.statuses.values())} sprites "
            "wedged at once; holding off recreate, check sprites.dev"
        )
    for name in due:
        echo(f"{name}: wedged {WEDGE_RECREATE_AFTER} wakes running, recreating")
        try:
            recreate_fn(name)
            report.recreated.append(name)
        except Exception as exc:  # noqa: BLE001 --- one bad recreate must not abort the rest
            echo(f"{name}: recreate failed: {exc!r}")
    return report


def stamp_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "slop" / "last-wake.json"


def write_stamp(statuses: dict[str, str], *, now: dt.datetime, path: Path | None = None) -> None:
    """Record that a wake finished and what each tick did. Written for a red
    run too: "no wake is firing" and "wakes fire and fail" are different
    outages, and `slop wake-check` needs to tell them apart."""
    target = path or stamp_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"finished_at": now.astimezone(dt.UTC).isoformat(), "statuses": statuses}
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    tmp.replace(target)
