"""Dead-man checks for the wake driver: is anything still ticking at all?

Every failure mode the driver already handles is one it observes *during* a wake:
`healing` classifies tick results, so it can only ever notice things that happen
while a wake is running. Two outages in 2026-07 were invisible to it because the
question was never asked:

- 10:02, the fleet went dark for 3h20m --- `slop-wake.timer` was stopped during
  `apt` maintenance and never restarted. A unit that never runs never fails, so
  no `OnFailure=` can catch this; only a separate clock can notice absence.
- 13:14, vLLM's EngineCore died and every tick failed for hours. Wakes *were*
  running and completing here, so freshness alone stays silent --- which is why
  the inference probe below is a first-class check and not a nicety.

So this asks three independent questions, and each one alone would have missed at
least one of those outages: is the timer armed, did a wake finish recently, and
can anything actually reach the model. It returns problems as strings for a
caller to print and exit non-zero on; on weddle the `OnFailure=unit-oncall@` /
`OnSuccess=unit-oncall-clear@` drop-ins turn that exit code into a deduped `nb`
todo, so the alerting half needs nothing new.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass
from pathlib import Path

# Statuses that mean a tick was actually serviced. `deferred` counts: the global
# slot cap turned it away on purpose, which is healthy behaviour, not a failure.
_HEALTHY_STATUSES = frozenset({"ok", "busy", "deferred"})


def stamp_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "slop" / "last-wake.json"


@dataclass(frozen=True)
class Probe:
    """Outcome of reaching for the inference endpoint."""

    ok: bool
    detail: str


def write_stamp(
    statuses: dict[str, str],
    *,
    now: dt.datetime,
    path: Path | None = None,
) -> None:
    """Record that a wake finished, and what each agent's tick did.

    Written unconditionally, including for an all-red run: for a dead-man check
    the signal is *completion*, and whether the ticks worked is a separate
    question answered by `statuses` and the inference probe. Deliberately not
    folded into `heal.json` --- that file's mtime happens to move on every wake
    today, but leaning on an incidental side effect is one refactor away from a
    watchdog that silently reports stale-as-fresh.
    """
    target = path or stamp_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "finished_at": now.astimezone(dt.UTC).isoformat(),
        "statuses": statuses,
    }
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    tmp.replace(target)


def read_stamp(path: Path | None = None) -> dict | None:
    """The last wake's stamp, or None if absent/corrupt."""
    target = path or stamp_path()
    try:
        data = json.loads(target.read_text())
    except FileNotFoundError, json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _format_age(seconds: float) -> str:
    if seconds < 90:
        return f"{int(seconds)}s"
    minutes = seconds / 60
    if minutes < 90:
        return f"{minutes:.0f}m"
    return f"{minutes / 60:.1f}h"


def problems(
    *,
    stamp: dict | None,
    now: dt.datetime,
    max_age: float,
    timer_active: bool,
    inference: Probe,
    timer_name: str = "slop-wake.timer",
) -> list[str]:
    """Everything wrong right now, as printable lines. Empty means healthy."""
    found: list[str] = []

    if not timer_active:
        found.append(
            f"{timer_name} is NOT active --- no wake will fire until it is started "
            f"(`systemctl --user start {timer_name}`). This is how the fleet went "
            "dark for 3h20m on 2026-07-28."
        )

    if stamp is None:
        found.append("no wake stamp found --- no wake has completed since this check was installed")
    else:
        raw = stamp.get("finished_at")
        finished = None
        if isinstance(raw, str):
            try:
                finished = dt.datetime.fromisoformat(raw)
            except ValueError:
                finished = None
        if finished is None:
            found.append(f"wake stamp has an unreadable finished_at: {raw!r}")
        else:
            if finished.tzinfo is None:
                finished = finished.replace(tzinfo=dt.UTC)
            age = (now - finished).total_seconds()
            if age > max_age:
                found.append(
                    f"last wake finished {_format_age(age)} ago, over the "
                    f"{_format_age(max_age)} limit --- ticks have stopped"
                )

        statuses = stamp.get("statuses")
        if isinstance(statuses, dict) and statuses:
            healthy = [n for n, s in statuses.items() if s in _HEALTHY_STATUSES]
            if not healthy:
                # Wakes completing with nothing working is exactly the shape of
                # the 13:14 vLLM outage, and freshness alone reads it as fine.
                broken = ", ".join(f"{n}={s}" for n, s in sorted(statuses.items()))
                found.append(f"every agent failed in the last wake: {broken}")

    if not inference.ok:
        found.append(f"inference endpoint unhealthy: {inference.detail}")

    return found
