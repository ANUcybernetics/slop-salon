"""The wake driver: classification, the wedge counter, and one full run."""

from __future__ import annotations

from pathlib import Path

from slop_salon import wake
from slop_salon.config import load_config
from slop_salon.sprites import ExecResult
from slop_salon.tick import SESSION_MARKER

UP = f"{SESSION_MARKER}\n"

OK = ExecResult(stdout=f"{UP}[main abc] session\n", stderr="", exit_code=0)
# The sprite never answered, so nothing of the tick ran.
WEDGE = ExecResult(stdout="", stderr="failed to connect: dial tcp: i/o timeout", exit_code=1)
DROPPED = ExecResult(stdout="", stderr="Error: connection closed", exit_code=1)
CLAUDE_ERR = ExecResult(
    stdout=f"{UP}API Error: 500\n", stderr="slop-tick: claude exited 1\n", exit_code=0
)
# The tick started, then git refused: the sprite is fine.
CONFLICT = ExecResult(
    stdout=UP, stderr="fatal: Exiting because of an unresolved conflict.", exit_code=128
)


def test_classify_names_the_four_shapes():
    assert wake.classify(OK) == "ok"
    assert wake.classify(WEDGE) == "wedge"
    assert wake.classify(CLAUDE_ERR) == "claude-err"
    assert wake.classify(CONFLICT) == "fail(128)"


def test_a_sprite_that_never_started_is_wedged_whatever_the_platform_called_it():
    # The three signatures seen so far, and one nobody has seen yet.
    for stderr in (
        "failed to connect: dial tcp: i/o timeout",
        "Error: connection closed",
        "failed to start sprite command",
        "Error: something the platform has not said before",
    ):
        assert wake.classify(ExecResult(stdout="", stderr=stderr, exit_code=1)) == "wedge"


def test_a_failure_after_the_sprite_started_is_not_wedged():
    # Same transport error, but the tick was already running: a recreate would
    # destroy work, and a retry would tick the agent twice.
    dropped_mid_tick = ExecResult(
        stdout=f"{UP}[main abc] session\n", stderr="Error: connection closed", exit_code=1
    )
    assert not wake.never_started(dropped_mid_tick)
    assert wake.classify(dropped_mid_tick) == "fail(1)"


def test_failure_tail_hides_the_session_marker():
    assert not any(SESSION_MARKER in line for line in wake.failure_tail(CONFLICT))


def test_failure_tail_digs_the_error_out_from_under_the_commit_summary():
    result = ExecResult(
        stdout="API Error: 500 context length\nAborted\n[main abc] session\n 1 file changed\n",
        stderr="To github.com:x\n   abc..def  main -> main\n",
        exit_code=0,
    )
    tail = wake.failure_tail(result)
    assert "[out] API Error: 500 context length" in tail
    assert tail[0].startswith("[err]")  # both streams, tagged


def test_wedge_counter_recreates_on_the_second_consecutive_wedge():
    state: dict[str, int] = {}
    assert wake.update_wedges(state, {"lou": "wedge", "mina": "ok"}) == ([], False)
    assert state == {"lou": 1, "mina": 0}
    assert wake.update_wedges(state, {"lou": "wedge", "mina": "ok"}) == (["lou"], False)
    assert state["lou"] == 0  # reset, so a recreate that does not stick waits again


def test_wedge_counter_resets_on_any_other_outcome():
    state = {"lou": 1}
    wake.update_wedges(state, {"lou": "claude-err"})
    assert state["lou"] == 0


def test_platform_incident_holds_off_however_long_agents_have_been_wedged():
    state = {"lou": 5, "mina": 5, "gert": 5}
    due, incident = wake.update_wedges(state, {"lou": "wedge", "mina": "wedge", "gert": "wedge"})
    assert due == [] and incident


class FakeSprites:
    def __init__(self, outcomes: dict[str, list[ExecResult]]):
        self.outcomes = outcomes
        self.calls: list[tuple[str, dict[str, str]]] = []

    def exec(self, sprite_id, command, env=None):
        self.calls.append((sprite_id, env or {}))
        queue = self.outcomes[sprite_id]
        return queue.pop(0) if len(queue) > 1 else queue[0]


def test_run_ticks_every_live_agent_with_its_own_env(registry):
    config = load_config(registry)
    sprites = FakeSprites({"lou": [OK], "mina": [OK], "gert": [OK]})
    lines: list[str] = []
    report = wake.run(config, sprites, recreate_fn=lambda n: None, echo=lines.append)
    assert report.ok and report.statuses == {"lou": "ok", "mina": "ok", "gert": "ok"}
    envs = dict(sprites.calls)
    assert envs["lou"]["AGENT_NAME"] == "lou" and envs["lou"]["BSKY_PASSWORD"] == "lou-pw"
    assert envs["gert"]["ANTHROPIC_AUTH_TOKEN"] == "sk-or-test"


def test_run_retries_a_transient_wedge_once_and_reports_it(registry):
    config = load_config(registry)
    sprites = FakeSprites({"lou": [WEDGE, OK], "mina": [OK], "gert": [OK]})
    lines: list[str] = []
    report = wake.run(config, sprites, only=["lou"], recreate_fn=lambda n: None, echo=lines.append)
    assert report.ok
    assert any("retried: no session" in line for line in lines)


def test_run_retries_a_dropped_cold_resume_and_does_not_count_it_as_a_wedge(registry, tmp_path):
    """The 2026-09-11 failure: the connection dropped while the sprite resumed,
    the second connect found it awake. Nothing is owed a recreate."""
    config = load_config(registry)
    sprites = FakeSprites({"lou": [DROPPED, OK], "mina": [OK], "gert": [OK]})
    state = tmp_path / "wedges.json"
    lines: list[str] = []
    report = wake.run(
        config, sprites, recreate_fn=lambda n: None, echo=lines.append, state_path=state
    )
    assert report.ok and report.statuses["lou"] == "ok"
    assert wake.load_wedges(state) == {"lou": 0, "mina": 0, "gert": 0}


def test_run_does_not_retry_a_tick_that_started(registry):
    """A second `slop-tick` would run beside the first, which the sprite may
    still be executing after the client gave up."""
    config = load_config(registry)
    sprites = FakeSprites({"lou": [CONFLICT, OK], "mina": [OK], "gert": [OK]})
    report = wake.run(
        config, sprites, only=["lou"], recreate_fn=lambda n: None, echo=lambda _: None
    )
    assert report.statuses["lou"] == "fail(128)"
    assert len(sprites.calls) == 1


def test_run_goes_red_on_a_claude_error_and_shows_why(registry):
    config = load_config(registry)
    sprites = FakeSprites({"lou": [CLAUDE_ERR], "mina": [OK], "gert": [OK]})
    lines: list[str] = []
    report = wake.run(config, sprites, recreate_fn=lambda n: None, echo=lines.append)
    assert report.failed == ["lou"]
    assert any("API Error: 500" in line for line in lines)


def test_run_recreates_after_two_wedged_wakes(registry, tmp_path):
    config = load_config(registry)
    state = tmp_path / "wedges.json"
    recreated: list[str] = []
    for _ in range(2):
        sprites = FakeSprites({"lou": [WEDGE], "mina": [OK], "gert": [OK]})
        report = wake.run(
            config, sprites, recreate_fn=recreated.append, echo=lambda _: None, state_path=state
        )
    assert recreated == ["lou"]
    assert report.recreated == ["lou"]
    assert not report.ok  # the wedged tick still failed this wake


def test_run_holds_off_when_the_platform_is_down(registry, tmp_path):
    config = load_config(registry)
    state = tmp_path / "wedges.json"
    recreated: list[str] = []
    lines: list[str] = []
    for _ in range(3):
        sprites = FakeSprites({"lou": [WEDGE], "mina": [WEDGE], "gert": [WEDGE]})
        report = wake.run(
            config, sprites, recreate_fn=recreated.append, echo=lines.append, state_path=state
        )
    assert recreated == [] and report.platform_incident
    assert any("PLATFORM INCIDENT" in line for line in lines)


def test_run_fails_before_any_sprite_when_a_secret_is_missing(registry, monkeypatch):
    monkeypatch.delenv("SLOP_GH_TOKEN")
    config = load_config(registry)
    sprites = FakeSprites({"lou": [OK], "mina": [OK], "gert": [OK]})
    try:
        wake.run(config, sprites, recreate_fn=lambda n: None, echo=lambda _: None)
    except RuntimeError as exc:
        assert "SLOP_GH_TOKEN" in str(exc)
    assert sprites.calls == []


def test_write_stamp_records_completion_even_for_a_red_run(tmp_path):
    import datetime as dt

    path = Path(tmp_path) / "last-wake.json"
    wake.write_stamp({"lou": "fail(1)"}, now=dt.datetime(2026, 9, 11, tzinfo=dt.UTC), path=path)
    assert '"lou": "fail(1)"' in path.read_text()
