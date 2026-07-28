"""The global tick cap has to hold across processes, not just within one run."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

from slop_salon import wake_slots


def test_slots_up_to_count_are_granted(tmp_path):
    with (
        wake_slots.acquire(2, slots_dir=tmp_path) as first,
        wake_slots.acquire(2, slots_dir=tmp_path) as second,
    ):
        assert first is True
        assert second is True


def test_one_more_than_count_defers(tmp_path):
    calls: list[float] = []
    clock = iter([0.0, 0.0, 5.0, 10.0, 10.0])

    with wake_slots.acquire(1, slots_dir=tmp_path) as held:
        assert held is True
        with wake_slots.acquire(
            1,
            wait=10.0,
            slots_dir=tmp_path,
            sleep=calls.append,
            monotonic=lambda: next(clock),
        ) as extra:
            assert extra is False
    # It waited rather than failing instantly, and gave up at the deadline.
    assert calls == [wake_slots.POLL_INTERVAL, wake_slots.POLL_INTERVAL]


def test_slot_is_released_on_exit(tmp_path):
    with wake_slots.acquire(1, slots_dir=tmp_path) as first:
        assert first is True
    with wake_slots.acquire(1, slots_dir=tmp_path) as second:
        assert second is True


def test_slot_is_released_when_the_body_raises(tmp_path):
    # A tick that dies must not strand its slot for the rest of the wake.
    try:
        with wake_slots.acquire(1, slots_dir=tmp_path):
            raise RuntimeError("tick blew up")
    except RuntimeError:
        pass
    with wake_slots.acquire(1, slots_dir=tmp_path) as after:
        assert after is True


def test_count_of_zero_never_blocks(tmp_path):
    # A misconfigured cap must not be the reason no agent ticks.
    with (
        wake_slots.acquire(0, slots_dir=tmp_path) as a,
        wake_slots.acquire(0, slots_dir=tmp_path) as b,
    ):
        assert a is True
        assert b is True


def test_cap_holds_across_processes(tmp_path):
    """The whole point: a *separate* wake run must see the slot as taken.

    Two overlapping `slop wake` processes are the case the in-process pool
    cannot bound, and the one that took the collective down.
    """
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            textwrap.dedent(f"""
                import time
                from pathlib import Path
                from slop_salon import wake_slots
                with wake_slots.acquire(1, slots_dir=Path({str(tmp_path)!r})) as got:
                    print("held" if got else "nope", flush=True)
                    time.sleep(30)
            """),
        ],
        stdout=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTHONPATH": "src"},
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "held"
        # The only slot is held by another process, so this run must defer.
        with wake_slots.acquire(1, wait=0.0, slots_dir=tmp_path) as mine:
            assert mine is False
    finally:
        holder.kill()
        holder.wait(timeout=10)

    # flock dies with the process, so the slot frees itself --- no reaping.
    with wake_slots.acquire(1, slots_dir=tmp_path) as after_death:
        assert after_death is True
