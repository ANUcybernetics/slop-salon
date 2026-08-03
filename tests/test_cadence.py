"""Tests for cadence parsing and the derived dead-man limit."""

from __future__ import annotations

import datetime as dt

import pytest

from slop_salon.cadence import (
    MIN_MAX_AGE,
    longest_gap,
    max_age_for,
    parse_elapses,
    render_dropin,
    spec_to_oncalendar,
)

# Real `systemd-analyze calendar --iterations=3 "*-*-* 00/6:00:00"` output.
ANALYSIS = """Normalized form: *-*-* 00/6:00:00
    Next elapse: Tue 2026-08-04 12:00:00 AEST
       (in UTC): Tue 2026-08-04 02:00:00 UTC
       From now: 2h 13min left
   Iteration #2: Tue 2026-08-04 18:00:00 AEST
       (in UTC): Tue 2026-08-04 08:00:00 UTC
       From now: 8h left
   Iteration #3: Wed 2026-08-05 00:00:00 AEST
       (in UTC): Tue 2026-08-04 14:00:00 UTC
       From now: 14h left
"""


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("6h", "*-*-* 00/6:00:00"),
        ("1h", "*-*-* 00/1:00:00"),
        ("30m", "*-*-* *:00/30:00"),
        # Anything that isn't the shorthand passes through, so an irregular
        # schedule (ticking only during waking hours) stays expressible.
        ("*-*-* 09,17:00:00", "*-*-* 09,17:00:00"),
    ],
)
def test_shorthand_expands_and_raw_specs_pass_through(spec, expected):
    assert spec_to_oncalendar(spec) == expected


@pytest.mark.parametrize("spec", ["0h", "24h", "0m", "60m"])
def test_out_of_range_shorthand_is_rejected(spec):
    """Caught before the drop-in is written --- a bad spec disarms the timer."""
    with pytest.raises(ValueError, match="cadence must be"):
        spec_to_oncalendar(spec)


def test_elapses_are_read_from_the_utc_lines():
    elapses = parse_elapses(ANALYSIS)
    assert len(elapses) == 3
    assert elapses[0] == dt.datetime(2026, 8, 4, 2, 0, tzinfo=dt.UTC)


def test_gap_is_the_widest_not_the_average():
    """An irregular schedule sized to its mean gap would cry wolf every night."""
    elapses = [
        dt.datetime(2026, 8, 4, 9, tzinfo=dt.UTC),
        dt.datetime(2026, 8, 4, 17, tzinfo=dt.UTC),  # 8h
        dt.datetime(2026, 8, 5, 9, tzinfo=dt.UTC),  # 16h
    ]
    assert longest_gap(elapses) == 16 * 3600


def test_gap_is_none_without_two_firings():
    assert longest_gap([]) is None
    assert longest_gap([dt.datetime(2026, 8, 4, tzinfo=dt.UTC)]) is None


def test_max_age_tracks_cadence_but_never_tightens_past_the_floor():
    """The coupling this whole module exists for.

    A 90-minute dead-man check against a 6-hourly timer files an oncall todo
    every hour forever, and an alert that always fires is one that gets
    silenced. The floor keeps a fast cadence from tightening the check past the
    ~30 minutes a single slow wake can itself take.
    """
    assert max_age_for(6 * 3600) == 18 * 3600  # three missed firings
    assert max_age_for(30 * 60) == MIN_MAX_AGE  # floored, not 45min
    assert max_age_for(None) == MIN_MAX_AGE


def test_dropin_clears_the_inherited_schedule_first():
    """systemd *appends* OnCalendar across drop-ins.

    Without the bare reset the unit fires on both the old schedule and the new
    one --- which looks like the change silently not working.
    """
    body = render_dropin("*-*-* 00/6:00:00")
    lines = [line for line in body.splitlines() if line.startswith("OnCalendar")]
    assert lines == ["OnCalendar=", "OnCalendar=*-*-* 00/6:00:00"]
