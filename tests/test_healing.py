"""Tests for the wake driver's wedged-sprite self-heal."""

from __future__ import annotations

import datetime as dt
import fcntl
import os

from slop_salon.healing import RECREATE_COOLDOWN, heal_wedged, is_wedge
from slop_salon.sprites import ExecResult

WEDGE = ExecResult(
    stdout="",
    stderr="Error: failed to start sprite command: failed to connect: i/o timeout",
    exit_code=1,
)
OK = ExecResult(stdout="ok", stderr="", exit_code=0)
CONFLICT = ExecResult(
    stdout="", stderr="fatal: Exiting because of an unresolved conflict.", exit_code=128
)
BUSY = ExecResult(
    stdout="", stderr="slop-tick: a tick is already running in this sprite, skipping", exit_code=75
)
# claude 400'd but slop-tick still exited 0 (it commits partial work).
CLAUDE_ERR = ExecResult(
    stdout="API Error: 400 ...", stderr="slop-tick: claude exited 1", exit_code=0
)
NOW = dt.datetime(2026, 6, 5, 12, 0, tzinfo=dt.UTC)


def _recorder():
    calls: list[str] = []
    return calls, calls.append


def _alerts():
    msgs: list[str] = []
    return msgs, msgs.append


def _heal(results, *, state, now=NOW, rec=None, alert=None, enabled=True):
    return heal_wedged(
        results,
        recreate_fn=rec or (lambda _n: None),
        alert_fn=alert or (lambda _m: None),
        now=now,
        enabled=enabled,
        state_path=state,
    )


def test_is_wedge_only_matches_the_connection_signature():
    assert is_wedge(WEDGE)
    assert not is_wedge(OK)
    assert not is_wedge(CONFLICT)  # merge conflict is not a wedge
    assert not is_wedge(ExecResult("", "some unrelated error", 1))


def test_busy_and_claude_failed_are_distinct_from_a_wedge():
    from slop_salon.healing import claude_failed, is_busy

    assert is_busy(BUSY)
    assert not is_busy(OK)
    assert claude_failed(CLAUDE_ERR)
    assert not claude_failed(OK)
    # A claude error is exit-0 with slop-tick's diagnostic --- reachable sprite,
    # so neither a wedge nor a busy skip. Keeping them disjoint matters: only
    # wedges recreate.
    assert not is_wedge(CLAUDE_ERR)
    assert not is_busy(CLAUDE_ERR)
    assert not claude_failed(WEDGE)


def test_first_wedge_does_not_recreate(tmp_path):
    recreated, rec = _recorder()
    report = _heal({"gert": WEDGE}, state=tmp_path / "heal.json", rec=rec)
    assert recreated == []
    assert report.wedged == ["gert"]


def test_second_consecutive_wedge_recreates(tmp_path):
    state = tmp_path / "heal.json"
    recreated, rec = _recorder()
    _heal({"gert": WEDGE}, state=state, rec=rec)
    report = _heal({"gert": WEDGE}, state=state, rec=rec)
    assert recreated == ["gert"]
    assert report.recreated == ["gert"]


def test_recovery_resets_the_consecutive_count(tmp_path):
    state = tmp_path / "heal.json"
    recreated, rec = _recorder()
    _heal({"gert": WEDGE}, state=state, rec=rec)  # 1
    _heal({"gert": OK}, state=state, rec=rec)  # recovered -> reset
    _heal({"gert": WEDGE}, state=state, rec=rec)  # 1 again, never reaches 2
    assert recreated == []


def test_platform_incident_holds_off(tmp_path):
    state = tmp_path / "heal.json"
    recreated, rec = _recorder()
    msgs, alert = _alerts()
    both = {"gert": WEDGE, "vita": WEDGE, "rahel": WEDGE}
    _heal(both, state=state, rec=rec, alert=alert)
    report = _heal(both, state=state, rec=rec, alert=alert)  # consecutive>=2, but 3 at once
    assert recreated == []
    assert report.platform_incident
    assert any("PLATFORM INCIDENT" in m for m in msgs)


def test_cooldown_blocks_a_repeat_then_allows_one_later(tmp_path):
    state = tmp_path / "heal.json"
    recreated, rec = _recorder()
    _heal({"gert": WEDGE}, state=state, rec=rec)
    _heal({"gert": WEDGE}, state=state, rec=rec)
    assert recreated == ["gert"]

    soon = NOW + dt.timedelta(minutes=30)
    _heal({"gert": WEDGE}, state=state, rec=rec, now=soon)
    report = _heal({"gert": WEDGE}, state=state, rec=rec, now=soon)
    assert recreated == ["gert"]  # still within cooldown
    assert "gert" in report.skipped_cooldown

    later = NOW + RECREATE_COOLDOWN + dt.timedelta(minutes=1)
    _heal({"gert": WEDGE}, state=state, rec=rec, now=later)
    assert recreated == ["gert", "gert"]


def test_kill_switch_detects_but_does_not_recreate(tmp_path):
    state = tmp_path / "heal.json"
    recreated, rec = _recorder()
    msgs, alert = _alerts()
    _heal({"gert": WEDGE}, state=state, rec=rec, alert=alert, enabled=False)
    _heal({"gert": WEDGE}, state=state, rec=rec, alert=alert, enabled=False)
    assert recreated == []
    assert any("disabled" in m for m in msgs)


def test_locked_out_when_another_wake_is_healing(tmp_path):
    state = tmp_path / "heal.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    held = os.open(str(state) + ".lock", os.O_CREAT | os.O_WRONLY, 0o600)
    fcntl.flock(held, fcntl.LOCK_EX)
    try:
        recreated, rec = _recorder()
        report = _heal({"gert": WEDGE, "vita": WEDGE}, state=state, rec=rec)
        assert report.locked_out
        assert recreated == []
        assert report.wedged == ["gert", "vita"]  # still reports what it saw
    finally:
        os.close(held)


def test_corrupt_state_file_is_treated_as_empty(tmp_path):
    # A truncated/garbage heal.json must not crash the wake --- _load_state has to
    # actually catch JSONDecodeError (not just FileNotFoundError) and start fresh.
    state = tmp_path / "heal.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text("{not valid json")
    recreated, rec = _recorder()
    report = _heal({"gert": WEDGE}, state=state, rec=rec)
    assert report.wedged == ["gert"]  # processed normally from a clean slate
    assert recreated == []


def test_busy_streak_alerts_at_threshold_without_recreating(tmp_path):
    from slop_salon.healing import BUSY_CONSECUTIVE_THRESHOLD

    state = tmp_path / "heal.json"
    recreated, rec = _recorder()
    msgs, alert = _alerts()

    # A couple of busies is just a slow tick overlapping the next wake --- silent.
    for _ in range(BUSY_CONSECUTIVE_THRESHOLD - 1):
        report = _heal({"mina": BUSY}, state=state, rec=rec, alert=alert)
        assert report.busy_stuck == []
    assert not any("stuck `busy`" in m for m in msgs)

    # Crossing the threshold means a tick wedged holding the lock --- alert.
    report = _heal({"mina": BUSY}, state=state, rec=rec, alert=alert)
    assert report.busy_stuck == ["mina"]
    assert any("stuck `busy`" in m for m in msgs)
    # A stuck flock is never auto-recreated --- the holder must be killed instead.
    assert recreated == []


def test_busy_streak_alert_fires_once_then_resets_on_recovery(tmp_path):
    from slop_salon.healing import BUSY_CONSECUTIVE_THRESHOLD

    state = tmp_path / "heal.json"
    msgs, alert = _alerts()

    for _ in range(BUSY_CONSECUTIVE_THRESHOLD + 3):
        _heal({"mina": BUSY}, state=state, alert=alert)
    # Only the exact crossing alerts --- not every wake past it.
    assert sum("stuck `busy`" in m for m in msgs) == 1

    _heal({"mina": OK}, state=state, alert=alert)  # a real tick resets the streak
    _heal({"mina": BUSY}, state=state, alert=alert)
    assert sum("stuck `busy`" in m for m in msgs) == 1


def test_claude_error_streak_alerts_without_recreating(tmp_path):
    from slop_salon.healing import CLAUDE_ERROR_CONSECUTIVE_THRESHOLD

    state = tmp_path / "heal.json"
    recreated, rec = _recorder()
    msgs, alert = _alerts()

    report = None
    for _ in range(CLAUDE_ERROR_CONSECUTIVE_THRESHOLD):
        report = _heal({"lelia": CLAUDE_ERR}, state=state, rec=rec, alert=alert)
    assert report.claude_failing == ["lelia"]
    assert any("claude errored" in m for m in msgs)
    # Recreating could land a newer, vLLM-incompatible claude --- must not.
    assert recreated == []


# --- Unrecognised failures ------------------------------------------------
#
# The healer used to classify only wedge/busy/claude-error, so any other
# failure incremented no counter and fired no alert --- indistinguishable from
# a healthy agent downstream. These pin the catch-all that closes that.

# mina's exact failure: a self-heal aborted after the destroy, leaving a sprite
# with no cloned repo. It fast-failed this on every wake for five days.
HALF_BUILT = ExecResult(
    stdout="", stderr="/usr/bin/bash: line 1: slop-tick: command not found", exit_code=127
)


def test_classification_is_a_clean_partition():
    from slop_salon.healing import claude_failed, is_busy, is_unclassified_failure

    # Exactly one classifier owns each result.
    for result in (WEDGE, BUSY, CLAUDE_ERR, HALF_BUILT, CONFLICT, OK):
        owners = [
            fn.__name__
            for fn in (is_wedge, is_busy, claude_failed, is_unclassified_failure)
            if fn(result)
        ]
        assert len(owners) <= 1, f"{result} claimed by {owners}"

    assert is_unclassified_failure(HALF_BUILT)
    assert is_unclassified_failure(CONFLICT)  # a merge conflict is a failure too
    assert not is_unclassified_failure(OK)
    assert not is_unclassified_failure(BUSY)
    assert not is_unclassified_failure(WEDGE)
    assert not is_unclassified_failure(CLAUDE_ERR)


def test_single_unrecognised_failure_stays_quiet(tmp_path):
    """One bad tick is a blip; the threshold exists so blips don't page."""
    msgs, alert = _alerts()
    report = _heal({"mina": HALF_BUILT}, state=tmp_path / "h.json", alert=alert)

    assert report.failing == []
    assert msgs == []


def test_repeated_unrecognised_failure_alerts_with_the_reason(tmp_path):
    state = tmp_path / "h.json"
    _heal({"mina": HALF_BUILT}, state=state)
    msgs, alert = _alerts()
    report = _heal({"mina": HALF_BUILT}, state=state, alert=alert)

    assert report.failing == ["mina"]
    assert len(msgs) == 1
    # The alert has to carry the reason: by definition nobody has a signature
    # for it, so a bare "mina is failing" sends the reader back to the journal.
    assert "slop-tick: command not found" in msgs[0]
    assert "127" in msgs[0]


def test_unrecognised_failure_is_never_auto_recreated(tmp_path):
    """We do not know what broke --- and a recreate is what broke mina."""
    state = tmp_path / "h.json"
    recreated, rec = _recorder()
    for _ in range(6):
        _heal({"mina": HALF_BUILT}, state=state, rec=rec)

    assert recreated == []


def test_a_long_outage_keeps_alerting(tmp_path):
    """Alerting once and falling silent is how five days looked like zero."""
    state = tmp_path / "h.json"
    msgs, alert = _alerts()
    for _ in range(20):
        _heal({"mina": HALF_BUILT}, state=state, alert=alert)

    # Loud at the threshold, then on a slow cadence --- not once, not every wake.
    assert 3 <= len(msgs) <= 8, f"{len(msgs)} alerts across 20 wakes"


def test_recovery_resets_the_failure_streak(tmp_path):
    state = tmp_path / "h.json"
    _heal({"mina": HALF_BUILT}, state=state)
    _heal({"mina": OK}, state=state)
    msgs, alert = _alerts()
    report = _heal({"mina": HALF_BUILT}, state=state, alert=alert)

    assert report.failing == []
    assert msgs == []


def test_one_agent_failing_does_not_mask_the_healthy_rest(tmp_path):
    """mina was 1 of 6, which is why the all-agents-failed check stayed green."""
    state = tmp_path / "h.json"
    fleet = dict.fromkeys(("lou", "gert", "vita", "lelia", "rahel"), OK)
    _heal({**fleet, "mina": HALF_BUILT}, state=state)
    report = _heal({**fleet, "mina": HALF_BUILT}, state=state)

    assert report.failing == ["mina"]
