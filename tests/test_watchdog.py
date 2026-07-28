"""Each check here corresponds to an outage that went unnoticed for hours."""

from __future__ import annotations

import datetime as dt

from slop_salon import watchdog

NOW = dt.datetime(2026, 7, 28, 14, 0, tzinfo=dt.UTC)
MAX_AGE = 90 * 60
OK = watchdog.Probe(ok=True, detail="200")


def _stamp(*, minutes_ago: float, statuses: dict[str, str] | None = None) -> dict:
    return {
        "finished_at": (NOW - dt.timedelta(minutes=minutes_ago)).isoformat(),
        "statuses": statuses if statuses is not None else {"lou": "ok", "mina": "ok"},
    }


def _problems(**kwargs):
    base = {
        "stamp": _stamp(minutes_ago=5),
        "now": NOW,
        "max_age": MAX_AGE,
        "timer_active": True,
        "inference": OK,
    }
    return watchdog.problems(**{**base, **kwargs})


def test_healthy_pipeline_reports_nothing():
    assert _problems() == []


def test_stopped_timer_is_caught():
    # The 10:02 outage: timer stopped during apt maintenance, never restarted.
    # No OnFailure= can catch this --- a unit that never runs never fails.
    found = _problems(timer_active=False)
    assert len(found) == 1
    assert "NOT active" in found[0]
    assert "slop-wake.timer" in found[0]


def test_the_message_names_the_timer_it_actually_checked():
    # A watchdog that names the wrong unit sends you to the wrong place.
    found = _problems(timer_active=False, timer_name="other-wake.timer")
    assert "other-wake.timer" in found[0]
    assert "slop-wake.timer" not in found[0]


def test_stale_stamp_is_caught():
    found = _problems(stamp=_stamp(minutes_ago=200))
    assert len(found) == 1
    assert "ticks have stopped" in found[0]


def test_fresh_stamp_just_inside_the_limit_is_fine():
    assert _problems(stamp=_stamp(minutes_ago=89)) == []


def test_missing_stamp_is_caught():
    found = _problems(stamp=None)
    assert len(found) == 1
    assert "no wake stamp" in found[0]


def test_unreadable_finished_at_is_caught_not_ignored():
    # A corrupt timestamp must never read as fresh --- that is a watchdog that
    # reports healthy while the fleet is dark.
    found = _problems(stamp={"finished_at": "not-a-date", "statuses": {"lou": "ok"}})
    assert len(found) == 1
    assert "unreadable finished_at" in found[0]


def test_naive_timestamp_is_treated_as_utc():
    naive = (NOW - dt.timedelta(minutes=5)).replace(tzinfo=None).isoformat()
    assert _problems(stamp={"finished_at": naive, "statuses": {"lou": "ok"}}) == []


def test_dead_engine_is_caught_even_when_wakes_are_fresh():
    # The 13:14 outage: wakes ran and completed on schedule for hours while every
    # tick failed, so freshness alone stays silent. This is why the inference
    # probe is a first-class check.
    found = _problems(inference=watchdog.Probe(ok=False, detail="/health 503 --- engine dead"))
    assert len(found) == 1
    assert "inference endpoint unhealthy" in found[0]


def test_all_agents_failing_is_caught_without_any_probe():
    # Defence in depth: even with the endpoint answering and the stamp fresh, a
    # wake where nothing worked is a problem.
    found = _problems(
        stamp=_stamp(minutes_ago=5, statuses={"lou": "claude-err", "mina": "fail(1)"})
    )
    assert len(found) == 1
    assert "every agent failed" in found[0]


def test_a_single_surviving_agent_is_not_flagged_as_all_failed():
    statuses = {"lou": "claude-err", "mina": "ok"}
    assert _problems(stamp=_stamp(minutes_ago=5, statuses=statuses)) == []


def test_deferred_counts_as_serviced():
    # Deferral is the slot cap working as designed, not a failure.
    statuses = {"lou": "deferred", "mina": "deferred"}
    assert _problems(stamp=_stamp(minutes_ago=5, statuses=statuses)) == []


def test_problems_accumulate():
    found = _problems(
        stamp=_stamp(minutes_ago=300),
        timer_active=False,
        inference=watchdog.Probe(ok=False, detail="unreachable"),
    )
    assert len(found) == 3


def test_stamp_roundtrips(tmp_path):
    path = tmp_path / "last-wake.json"
    watchdog.write_stamp({"lou": "ok", "mina": "busy"}, now=NOW, path=path)
    stamp = watchdog.read_stamp(path)
    assert stamp is not None
    assert stamp["statuses"] == {"lou": "ok", "mina": "busy"}
    assert (
        watchdog.problems(stamp=stamp, now=NOW, max_age=MAX_AGE, timer_active=True, inference=OK)
        == []
    )


def test_read_stamp_tolerates_a_truncated_write(tmp_path):
    path = tmp_path / "last-wake.json"
    path.write_text('{"finished_at": "2026-07-28T')
    assert watchdog.read_stamp(path) is None


def test_read_stamp_tolerates_a_missing_file(tmp_path):
    assert watchdog.read_stamp(tmp_path / "nope.json") is None
