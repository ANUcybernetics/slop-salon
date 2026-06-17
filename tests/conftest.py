"""Shared unit-test fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_heal_state(tmp_path, monkeypatch):
    """Keep wake-driver self-heal state out of the real ~/.local/state.

    `heal_wedged` defaults its state file to `$XDG_STATE_HOME/slop/heal.json`,
    and the CLI wake tests drive that default path. On the admin box that file
    is live operational state --- and now that a crossed busy/claude-error
    threshold curls the alert webhook, an un-isolated test run could both
    clobber real state and fire a spurious alert. Redirect it per-test.
    """
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg_state"))
