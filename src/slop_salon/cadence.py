"""Read and change how often the wake timer fires.

Cadence is the salon's metabolism and the only lever with real leverage over
cost --- a tick's price is dominated by a fixed floor (the ~29k prompt prefix
plus the mandatory reads in the numbered routine), so a do-nothing rest tick
costs about 60% of one that makes and posts a piece. You cannot make ticks much
cheaper, only rarer. That makes this a knob worth turning often, which is why it
lives behind a command instead of a unit file you have to remember to reinstall.

The staleness limit in `slop wake-check` is **derived** from the timer rather
than configured beside it. The two are the same fact stated twice, and a
90-minute dead-man check against a 6-hourly timer would file an oncall todo
every hour forever --- the kind of mismatch that gets a real alert silenced.
"""

from __future__ import annotations

import datetime as dt
import itertools
import re
import subprocess

DROPIN_DIR = "slop-wake.timer.d"
DROPIN_NAME = "cadence.conf"

# systemd *appends* OnCalendar across drop-ins, so setting a new schedule
# without first clearing the list leaves the unit firing on both. The empty
# assignment is the documented reset and is load-bearing.
DROPIN_TEMPLATE = """# Written by `slop cadence`. Edit via that command, not by hand.
#
# The bare `OnCalendar=` first is a reset: systemd accumulates OnCalendar
# entries across drop-ins, so without it this schedule would be *added* to the
# one in slop-wake.timer rather than replacing it.
[Timer]
OnCalendar=
OnCalendar={oncalendar}
"""

_SHORTHAND = re.compile(r"^(\d+)([mh])$")
_UTC_LINE = re.compile(r"\(in UTC\):\s+\w+ (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) UTC")

# Same rule the 30-minute default was chosen under: tolerate three missed
# firings before calling the pipeline dead. Kept as a floor so a fast cadence
# never tightens the check past the ~30 minutes a single slow wake can itself
# take.
MISSED_FIRINGS = 3
MIN_MAX_AGE = 90 * 60.0


def spec_to_oncalendar(spec: str) -> str:
    """Turn `6h` / `30m` into a systemd OnCalendar; pass anything else through.

    The shorthand covers the only two shapes we ever want --- every N hours or
    every N minutes --- while a raw OnCalendar stays available for the irregular
    case (say, ticking only during waking hours).
    """
    spec = spec.strip()
    match = _SHORTHAND.match(spec)
    if not match:
        return spec
    n, unit = int(match.group(1)), match.group(2)
    if unit == "h":
        if not 1 <= n <= 23:
            raise ValueError(f"hourly cadence must be 1-23h, got {n}h")
        return f"*-*-* 00/{n}:00:00"
    if not 1 <= n <= 59:
        raise ValueError(f"minute cadence must be 1-59m, got {n}m")
    return f"*-*-* *:00/{n}:00"


def parse_elapses(text: str) -> list[dt.datetime]:
    """UTC firing times out of `systemd-analyze calendar` output."""
    return [
        dt.datetime.strptime(m, "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.UTC)
        for m in _UTC_LINE.findall(text)
    ]


def longest_gap(elapses: list[dt.datetime]) -> float | None:
    """The widest interval between consecutive firings, in seconds.

    The widest, not the average: an irregular schedule (`09,17:00:00`) has an
    8-hour gap and a 16-hour one, and a staleness limit sized to the mean would
    cry wolf every night.
    """
    if len(elapses) < 2:
        return None
    return max((b - a).total_seconds() for a, b in itertools.pairwise(elapses))


def max_age_for(gap_seconds: float | None) -> float:
    """Staleness limit for `wake-check`, given the timer's widest gap."""
    if not gap_seconds:
        return MIN_MAX_AGE
    return max(MIN_MAX_AGE, gap_seconds * MISSED_FIRINGS)


def render_dropin(oncalendar: str) -> str:
    return DROPIN_TEMPLATE.format(oncalendar=oncalendar)


# --- Talking to systemd (impure; kept thin so the logic above stays testable) ---


def analyse(oncalendar: str, iterations: int = 4) -> str:
    """Run `systemd-analyze calendar`, raising if the spec is invalid.

    Validating here means a typo is caught before it is written to disk, rather
    than silently disarming the timer on the next daemon-reload.
    """
    result = subprocess.run(
        ["systemd-analyze", "calendar", f"--iterations={iterations}", oncalendar],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError(f"invalid OnCalendar {oncalendar!r}: {result.stderr.strip()}")
    return result.stdout


def active_oncalendar(timer: str = "slop-wake.timer") -> str | None:
    """The schedule the timer is actually running, drop-ins included."""
    result = subprocess.run(
        ["systemctl", "--user", "show", timer, "-p", "TimersCalendar"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    found = re.findall(r"OnCalendar=([^;}]+)", result.stdout)
    return found[-1].strip() if found else None


def current_max_age(timer: str = "slop-wake.timer") -> float:
    """Staleness limit derived from whatever the timer is currently set to."""
    oncalendar = active_oncalendar(timer)
    if not oncalendar:
        return MIN_MAX_AGE
    try:
        return max_age_for(longest_gap(parse_elapses(analyse(oncalendar))))
    except ValueError, OSError:
        return MIN_MAX_AGE
