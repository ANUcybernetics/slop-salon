"""A cap on concurrent ticks that holds *across* overlapping wake runs.

`WAKE_CONCURRENCY` bounds the `ThreadPoolExecutor` inside one `slop wake`, which
is not the same thing as bounding load on the shared vLLM. `slop-wake.service`
dispatches each firing as a transient unit precisely so a slow run never blocks
the next one, so two or more runs are routinely in flight at once --- and each
gets its own pool, so the documented cap silently does not hold.

On 2026-07-28 the 12:58 catch-up run held four ticks while the 13:03 firing
picked up the two agents still queued behind them: six concurrent ~31k-token
requests against a cap of four. Minutes later a TP worker hung and EngineCore
died, taking the collective down for hours. That the cap exists for exactly this
reason and wasn't in force is the bug, whether or not 6-vs-4 was the trigger.

A cap has to live somewhere every run can see it, so it is a set of `count` lock
files: a tick holds one for its duration, and a run that cannot get one within
its wait budget **defers** that agent rather than piling on. Deferring is cheap
--- the next firing is ~30 min away and the in-sprite flock already prevents
double-ticking --- whereas piling on is the thing that hurt.

`flock` releases when the holding process dies, so a killed or timed-out wake
can never strand a slot; there is no staleness to reap.
"""

from __future__ import annotations

import fcntl
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

# How long a tick waits for a free slot before giving up and deferring. Sized so
# a single run never defers spuriously: within one run the pool is capped at the
# same number as there are slots, so a tick only ever waits when another run
# holds them, and ticks run 2-9 min (30 min hard cap).
DEFAULT_SLOT_WAIT = 900.0

# Re-check cadence while waiting. flock has no "wait on any of N" primitive, so
# this polls; 5s is negligible against multi-minute ticks.
POLL_INTERVAL = 5.0


def _slots_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "slop" / "wake-slots"


def slot_wait_from_env() -> float:
    """`SLOP_WAKE_SLOT_WAIT` (seconds), falling back to DEFAULT_SLOT_WAIT.

    An unparseable value falls back rather than raising: this knob must never be
    the reason a wake refuses to run.
    """
    raw = os.environ.get("SLOP_WAKE_SLOT_WAIT")
    if not raw:
        return DEFAULT_SLOT_WAIT
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_SLOT_WAIT
    return value if value > 0 else DEFAULT_SLOT_WAIT


@contextmanager
def acquire(
    count: int,
    *,
    wait: float = DEFAULT_SLOT_WAIT,
    slots_dir: Path | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> Iterator[bool]:
    """Hold one of `count` process-wide slots for the body of the `with`.

    Yields True if a slot was acquired (the caller should do its work) or False
    if none came free within `wait` (the caller should defer). `sleep` and
    `monotonic` are injectable so tests don't have to spend real time.
    """
    if count <= 0:
        # No cap configured --- never block a tick on a misconfigured knob.
        yield True
        return

    directory = Path(slots_dir) if slots_dir else _slots_dir()
    directory.mkdir(parents=True, exist_ok=True)
    deadline = monotonic() + wait
    held: int | None = None
    try:
        while True:
            for index in range(count):
                # flock is tied to the open file description, not the process, so
                # each attempt needs its own open() --- and two threads in one
                # wake contend correctly rather than both "succeeding".
                candidate = os.open(
                    str(directory / f"slot-{index}.lock"), os.O_CREAT | os.O_WRONLY, 0o600
                )
                try:
                    fcntl.flock(candidate, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    os.close(candidate)
                    continue
                held = candidate
                break
            if held is not None:
                break
            # Never sleep past the deadline: a short wait must return promptly
            # rather than always costing a full poll interval.
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            sleep(min(POLL_INTERVAL, remaining))
        yield held is not None
    finally:
        if held is not None:
            # Closing the descriptor releases the flock.
            os.close(held)
