"""Dead-man check: is anything still ticking at all?

Everything `slop wake` knows, it learns during a wake, so it is blind to the
pipeline not running. Two independent questions catch the two outages that
have actually happened: has the wake timer been stopped longer than a pause
takes (stopping it is also how the fleet is held still on purpose, so the
question is how long, not whether), and did a wake finish recently. A wake in
which every agent failed is flagged too, since freshness alone reads that as
fine. Problems come back as strings; the caller prints them and exits
non-zero, and the systemd `OnFailure=` oncall pattern does the alerting.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from .wake import stamp_path


def read_stamp(path: Path | None = None) -> dict | None:
    target = path or stamp_path()
    try:
        data = json.loads(target.read_text())
    except FileNotFoundError, json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def format_age(seconds: float) -> str:
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
    timer_stopped_for: float | None,
    timer_grace: float,
    timer_name: str = "slop-wake.timer",
) -> list[str]:
    """Everything wrong right now, as printable lines. Empty means healthy.
    `timer_stopped_for` is None while the timer is armed."""
    found: list[str] = []

    if timer_stopped_for is not None and timer_stopped_for > timer_grace:
        found.append(
            f"{timer_name} has been stopped for {format_age(timer_stopped_for)}, past the "
            f"{format_age(timer_grace)} a pause is given; no wake will fire until it is "
            f"started (`systemctl --user start {timer_name}`)"
        )

    if stamp is None:
        found.append("no wake stamp found; no wake has completed since this check was installed")
        return found

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
                f"last wake finished {format_age(age)} ago, over the {format_age(max_age)} "
                "limit; ticks have stopped"
            )

    statuses = stamp.get("statuses")
    if isinstance(statuses, dict) and statuses and not any(s == "ok" for s in statuses.values()):
        broken = ", ".join(f"{n}={s}" for n, s in sorted(statuses.items()))
        found.append(f"every agent failed in the last wake: {broken}")
    return found
