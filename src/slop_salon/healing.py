"""Detect wedged sprites during a wake and self-heal by recreating them.

A wedged sprite (see the `troubleshoot` skill / project memory) fails every
tick with a connection i/o-timeout to its exec proxy --- distinct from a merge
conflict (exit 128, fast) or an auth error. `slop wake` classifies each tick
result and hands them here; this module recreates an agent only once the wedge
has persisted, with guardrails so a transient blip or a platform-wide incident
doesn't trigger a recreate-storm:

- `WEDGE_CONSECUTIVE_THRESHOLD` consecutive wedged wakes before acting (a
  one-off i/o blip is ignored);
- if `PLATFORM_INCIDENT_THRESHOLD`+ agents are wedged at once it holds off and
  alerts (recreating won't help a platform outage, and could make it worse);
- a per-agent `RECREATE_COOLDOWN` so a recreate that doesn't stick won't loop;
- a file lock so overlapping wakes never recreate the same agent twice;
- a `SLOP_AUTOHEAL=0` kill-switch (still detects + alerts, just won't recreate).

State lives in `~/.local/state/slop/heal.json`.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .sprites import ExecResult

WEDGE_CONSECUTIVE_THRESHOLD = 2
PLATFORM_INCIDENT_THRESHOLD = 3
RECREATE_COOLDOWN = dt.timedelta(hours=2)

# The sprites-CLI connection-failure signature (exec proxy unreachable).
_WEDGE_MARKERS = ("failed to connect", "failed to start sprite command", "i/o timeout")


def _state_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "slop" / "heal.json"


def is_wedge(result: ExecResult) -> bool:
    """True if a failed tick matches the wedged-sprite signature."""
    if result.exit_code == 0:
        return False
    blob = f"{result.stderr}\n{result.stdout}".lower()
    return any(marker in blob for marker in _WEDGE_MARKERS)


@dataclass
class HealReport:
    wedged: list[str] = field(default_factory=list)
    recreated: list[str] = field(default_factory=list)
    skipped_cooldown: list[str] = field(default_factory=list)
    platform_incident: bool = False
    locked_out: bool = False


def _load_state(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError, json.JSONDecodeError:
        data = {}
    data.setdefault("agents", {})
    return data


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
    tmp.replace(path)


def heal_wedged(
    results: dict[str, ExecResult],
    *,
    recreate_fn: Callable[[str], None],
    alert_fn: Callable[[str], None],
    now: dt.datetime,
    enabled: bool = True,
    state_path: Path | None = None,
) -> HealReport:
    """Update per-agent wedge state and recreate agents wedged past threshold.

    `results` maps agent name -> this wake's tick result. Returns a HealReport.
    Ordinary failures (a recreate that errors) are reported via `alert_fn`, not
    raised, so this never crashes the caller.
    """
    path = state_path or _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    wedged_now = sorted(name for name, r in results.items() if is_wedge(r))
    report = HealReport(wedged=wedged_now)

    # Only one wake heals at a time --- overlapping wakes must not race on the
    # state file or recreate the same agent twice.
    lock_fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            report.locked_out = True
            return report

        state = _load_state(path)
        agents = state["agents"]
        for name, result in results.items():
            entry = agents.setdefault(name, {})
            if is_wedge(result):
                entry["consecutive_wedges"] = entry.get("consecutive_wedges", 0) + 1
            else:
                entry["consecutive_wedges"] = 0

        if len(wedged_now) >= PLATFORM_INCIDENT_THRESHOLD:
            report.platform_incident = True
            alert_fn(
                f"PLATFORM INCIDENT: {len(wedged_now)} sprites wedged at once "
                f"({', '.join(wedged_now)}) --- holding off auto-recreate; check sprites.dev."
            )
            _save_state(path, state)
            return report

        for name in wedged_now:
            entry = agents[name]
            if entry.get("consecutive_wedges", 0) < WEDGE_CONSECUTIVE_THRESHOLD:
                continue
            last = entry.get("last_recreate")
            if last and (now - dt.datetime.fromisoformat(last)) < RECREATE_COOLDOWN:
                report.skipped_cooldown.append(name)
                alert_fn(
                    f"{name} still wedged but was recreated at {last} "
                    f"(within {RECREATE_COOLDOWN}) --- not retrying; likely a platform issue."
                )
                continue
            if not enabled:
                alert_fn(
                    f"{name} wedged {WEDGE_CONSECUTIVE_THRESHOLD}+ wakes; "
                    f"auto-heal disabled (SLOP_AUTOHEAL=0) --- not recreating."
                )
                continue
            # Claim before the (slow) recreate so an overlapping wake skips it.
            entry["last_recreate"] = now.isoformat()
            entry["consecutive_wedges"] = 0
            _save_state(path, state)
            alert_fn(
                f"AUTO-HEAL: {name} wedged {WEDGE_CONSECUTIVE_THRESHOLD}+ wakes --- recreating."
            )
            try:
                recreate_fn(name)
                report.recreated.append(name)
                alert_fn(f"AUTO-HEAL: {name} recreated.")
            except Exception as exc:  # noqa: BLE001 --- one bad recreate must not abort the rest
                alert_fn(f"AUTO-HEAL FAILED for {name}: {exc!r}")

        _save_state(path, state)
        return report
    finally:
        os.close(lock_fd)
