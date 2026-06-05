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
