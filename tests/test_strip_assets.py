"""Tests for the assets/ history-rewrite migration (task-11).

The subprocess-heavy path (mirror clone, filter-repo, force-push) is exercised
by the runbook, not here; these cover the two pieces with real logic --- the
size formatter and the sprite pre-flight guards that stop a rewrite from
destroying un-pushed work.
"""

from __future__ import annotations

import pytest

from slop_salon.sprites import ExecResult
from slop_salon.strip_assets import _human, _preflight_sprite


def test_human_scales_units():
    assert _human(512) == "512.0B"
    assert _human(2048) == "2.0KiB"
    assert _human(5 * 1024 * 1024) == "5.0MiB"
    assert _human(3 * 1024**3) == "3.0GiB"


class _FakeSprites:
    """Return a scripted ExecResult per exec, matching on a substring of the cmd."""

    def __init__(self, rules: list[tuple[str, ExecResult]]):
        self.rules = rules
        self.calls: list[str] = []

    def exec(self, sprite_id: str, command: list[str]) -> ExecResult:
        script = command[-1]
        self.calls.append(script)
        for needle, result in self.rules:
            if needle in script:
                return result
        raise AssertionError(f"no rule matched: {script!r}")


def test_preflight_aborts_when_a_tick_is_running():
    sprites = _FakeSprites([("pgrep", ExecResult("12345\n", "", 0))])
    with pytest.raises(SystemExit, match="a tick is running"):
        _preflight_sprite(sprites, "lou", "~/slop-salon-lou")


def test_preflight_aborts_on_unpushed_commits():
    sprites = _FakeSprites(
        [
            ("pgrep", ExecResult("", "", 0)),
            ("rev-list", ExecResult("3\n", "", 0)),
        ]
    )
    with pytest.raises(SystemExit, match="3 commit"):
        _preflight_sprite(sprites, "lou", "~/slop-salon-lou")


def test_preflight_aborts_when_the_check_itself_fails():
    sprites = _FakeSprites(
        [
            ("pgrep", ExecResult("", "", 0)),
            ("rev-list", ExecResult("", "fatal: not a git repository", 128)),
        ]
    )
    with pytest.raises(SystemExit, match="could not check"):
        _preflight_sprite(sprites, "lou", "~/slop-salon-lou")


def test_preflight_passes_when_idle_and_pushed():
    sprites = _FakeSprites(
        [
            ("pgrep", ExecResult("", "", 0)),
            ("rev-list", ExecResult("0\n", "", 0)),
        ]
    )
    _preflight_sprite(sprites, "lou", "~/slop-salon-lou")  # no raise
    assert any("fetch" in c for c in sprites.calls)
