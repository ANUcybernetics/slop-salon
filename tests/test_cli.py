"""Tests for the `slop` admin CLI."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from slop_salon.cli import _failure_tail, app
from slop_salon.sprites import ExecResult

runner = CliRunner()


@pytest.fixture
def fake_config(tmp_path, monkeypatch):
    cfg = tmp_path / "slop_salon.toml"
    cfg.write_text(
        """
[agents.lou]
handle = "lou.slopsalon.art"
github_repo = "ANUcybernetics/slop-salon-lou"
sprite_id = "spr_abc"
siblings = ["other"]

[agents.other]
handle = "other.slopsalon.art"
github_repo = "ANUcybernetics/slop-salon-other"
sprite_id = "spr_xyz"
siblings = ["lou"]
"""
    )
    monkeypatch.chdir(tmp_path)
    return cfg


def test_status_lists_agents(fake_config):
    with patch("slop_salon.cli.SpritesClient") as mock_class:
        instance = MagicMock()
        instance.get_status.return_value = "running"
        mock_class.return_value = instance

        result = runner.invoke(app, ["status"])

        assert result.exit_code == 0, result.output
        assert "lou" in result.output
        assert "other" in result.output
        assert "running" in result.output


def _transcript_stream() -> str:
    """A delimited two-turn session as `slop logs` streams it back from a sprite."""
    return "\n".join(
        [
            "<<<SLOPLOG abcd1234-0000.jsonl 2026-06-02T10:07:10Z>>>",
            json.dumps(
                {
                    "type": "user",
                    "timestamp": "2026-06-02T10:02:03Z",
                    "message": {"role": "user", "content": "tick"},
                }
            ),
            json.dumps(
                {
                    "type": "assistant",
                    "timestamp": "2026-06-02T10:02:30Z",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "thinking", "thinking": "Let me follow the tick procedure."},
                            {"type": "tool_use", "name": "Bash", "input": {"command": "bsky feed"}},
                            {"type": "text", "text": "posted a piece about eigenvectors"},
                        ],
                    },
                }
            ),
            json.dumps(
                {
                    "type": "user",
                    "timestamp": "2026-06-02T10:02:40Z",
                    "message": {
                        "role": "user",
                        "content": [{"type": "tool_result", "content": "3 new notifications"}],
                    },
                }
            ),
        ]
    )


def test_logs_renders_transcript_from_sprite(fake_config):
    with patch("slop_salon.cli.SpritesClient") as mock_class:
        instance = MagicMock()
        instance.exec.return_value = MagicMock(stdout=_transcript_stream(), stderr="", exit_code=0)
        mock_class.return_value = instance

        result = runner.invoke(app, ["logs", "lou"])

        assert result.exit_code == 0, result.output
        # Exec'd against the right sprite, reading the real transcript dir
        instance.exec.assert_called_once()
        sprite_id, command = instance.exec.call_args[0]
        assert sprite_id == "spr_abc"
        remote = " ".join(command)
        assert ".claude/projects" in remote
        assert "slop-salon-lou" in remote
        # Rendered as readable turns, not raw JSON
        assert "abcd1234" in result.output  # session id in the header
        assert "tick" in result.output
        assert "posted a piece about eigenvectors" in result.output
        assert "Bash" in result.output
        assert "3 new notifications" in result.output
        assert "10:02:30" in result.output
        assert '"type"' not in result.output  # JSON was parsed, not dumped


def test_logs_reports_no_transcripts(fake_config):
    with patch("slop_salon.cli.SpritesClient") as mock_class:
        instance = MagicMock()
        instance.exec.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_class.return_value = instance

        result = runner.invoke(app, ["logs", "lou"])

        assert result.exit_code == 0, result.output
        assert "no transcripts" in result.output.lower()


def test_logs_sessions_option_sets_head_count(fake_config):
    with patch("slop_salon.cli.SpritesClient") as mock_class:
        instance = MagicMock()
        instance.exec.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_class.return_value = instance

        runner.invoke(app, ["logs", "lou", "-n", "3"])

        remote = " ".join(instance.exec.call_args[0][1])
        assert "head -3" in remote


def test_render_transcripts_is_pure():
    from slop_salon.cli import _render_transcripts

    out = _render_transcripts(_transcript_stream())
    assert "-- tick abcd1234" in out
    assert "posted a piece about eigenvectors" in out
    assert "10:02:30" in out
    # No delimiter -> no sessions
    assert _render_transcripts("just some noise\nwithout a header") == ""


def test_diff_runs_git_in_sprite(fake_config):
    with patch("slop_salon.cli.SpritesClient") as mock_class:
        instance = MagicMock()
        instance.exec.return_value = MagicMock(
            stdout="diff --git a/x b/x\n+hi", stderr="", exit_code=0
        )
        mock_class.return_value = instance

        result = runner.invoke(app, ["diff", "lou", "--since", "1.day"])

        assert result.exit_code == 0, result.output
        assert "+hi" in result.output


def test_feed_all_agents(fake_config, httpx_mock):
    httpx_mock.add_response(
        json={
            "feed": [{"post": {"record": {"text": "lou post", "createdAt": "2026-04-30T10:00Z"}}}]
        }
    )
    httpx_mock.add_response(
        json={
            "feed": [{"post": {"record": {"text": "other post", "createdAt": "2026-04-30T11:00Z"}}}]
        }
    )

    result = runner.invoke(app, ["feed"])

    assert result.exit_code == 0, result.output
    assert "lou post" in result.output
    assert "other post" in result.output
    assert "2026-04-30T10:00Z" in result.output

    requests = httpx_mock.get_requests()
    assert len(requests) == 2
    handles = {r.url.params["actor"] for r in requests}
    assert handles == {"lou.slopsalon.art", "other.slopsalon.art"}


def test_feed_single_agent(fake_config, httpx_mock):
    httpx_mock.add_response(
        json={
            "feed": [{"post": {"record": {"text": "lou's post", "createdAt": "2026-04-30T10:00Z"}}}]
        }
    )

    result = runner.invoke(app, ["feed", "lou", "--limit", "5"])

    assert result.exit_code == 0, result.output
    assert "lou's post" in result.output

    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    assert requests[0].url.params["actor"] == "lou.slopsalon.art"
    assert requests[0].url.params["limit"] == "5"
    assert requests[0].url.params["filter"] == "posts_and_author_threads"


def test_feed_handles_http_error(fake_config, httpx_mock):
    httpx_mock.add_response(status_code=500, text="server error")

    result = runner.invoke(app, ["feed", "lou"])

    assert result.exit_code == 0, result.output
    assert "lou" in result.output
    assert "error" in result.output.lower()


def test_talk_runs_slop_tick_with_prompt(fake_config):
    with patch("slop_salon.cli.SpritesClient") as mock_class:
        instance = MagicMock()
        instance.exec.return_value = MagicMock(stdout="(claude output)", stderr="", exit_code=0)
        mock_class.return_value = instance

        result = runner.invoke(app, ["talk", "lou", "your last three posts felt similar"])

        assert result.exit_code == 0, result.output
        assert "(claude output)" in result.output

        cmd = instance.exec.call_args[0][1]
        # The prompt should appear in the exec command
        joined = " ".join(cmd)
        assert "slop-tick" in joined
        assert "your last three posts felt similar" in joined


@pytest.fixture
def live_config(tmp_path, monkeypatch):
    cfg = tmp_path / "slop_salon.toml"
    cfg.write_text(
        """
[agents.lou]
handle = "lou.slopsalon.art"
github_repo = "ANUcybernetics/slop-salon-lou"
sprite_id = "spr_lou"
siblings = ["mina"]
live = true

[agents.mina]
handle = "mina.slopsalon.art"
github_repo = "ANUcybernetics/slop-salon-mina"
sprite_id = "spr_mina"
siblings = ["lou"]
live = true
"""
    )
    monkeypatch.chdir(tmp_path)
    return cfg


def _wake_with_outcomes(outcomes):
    with patch("slop_salon.cli.SpritesClient") as mock_class:
        instance = MagicMock()
        instance.exec.side_effect = lambda sprite_id, cmd: outcomes[sprite_id]
        mock_class.return_value = instance
        return runner.invoke(app, ["wake"])


def test_wake_busy_agent_is_skipped_not_failed(live_config):
    # mina is mid-tick from an overlapping run: slop-tick exits 75.
    result = _wake_with_outcomes(
        {
            "spr_lou": MagicMock(stdout="", stderr="", exit_code=0),
            "spr_mina": MagicMock(
                stdout="",
                stderr="slop-tick: a tick is already running in this sprite, skipping",
                exit_code=75,
            ),
        }
    )

    # Busy is a clean skip --- the run stays green and is not a failure.
    assert result.exit_code == 0, result.output
    assert "busy" in result.output
    assert "fail" not in result.output


def test_wake_genuine_failure_makes_run_red(live_config):
    result = _wake_with_outcomes(
        {
            "spr_lou": MagicMock(stdout="", stderr="", exit_code=0),
            "spr_mina": MagicMock(stdout="", stderr="boom", exit_code=1),
        }
    )

    assert result.exit_code == 1, result.output
    assert "fail(1)" in result.output


def test_wake_surfaces_claude_error_instead_of_a_false_ok(live_config):
    # slop-tick exits 0 even though claude 400'd: the tick "succeeded" but did
    # nothing. It must not read as a healthy `ok` (lelia hid here for ~3.5 days).
    result = _wake_with_outcomes(
        {
            "spr_lou": MagicMock(stdout="", stderr="", exit_code=0),
            "spr_mina": MagicMock(
                stdout="API Error: 400 ...",
                stderr="slop-tick: claude exited 1",
                exit_code=0,
            ),
        }
    )

    assert "claude-err" in result.output
    assert "ok" in result.output  # lou still reads as ok
    # A do-nothing tick reddens the run, the same as a hard failure would.
    assert result.exit_code == 1, result.output


def _wedge_result():
    """An ExecResult carrying the cold-start exec-proxy wedge signature."""
    return MagicMock(
        stdout="",
        stderr="failed to start sprite command: failed to connect: "
        "read tcp 10.46.16.55:43744->169.155.48.226:443: i/o timeout",
        exit_code=1,
    )


def test_exec_tick_with_retry_absorbs_transient_wedge():
    from slop_salon.cli import _exec_tick_with_retry

    ok = MagicMock(stdout="", stderr="", exit_code=0)
    sprites = MagicMock()
    sprites.exec.side_effect = [_wedge_result(), ok]

    result, retried = _exec_tick_with_retry(sprites, "spr_x")

    assert retried is True
    assert result is ok
    assert sprites.exec.call_count == 2


def test_exec_tick_with_retry_no_retry_when_first_attempt_clean():
    from slop_salon.cli import _exec_tick_with_retry

    ok = MagicMock(stdout="", stderr="", exit_code=0)
    sprites = MagicMock()
    sprites.exec.side_effect = [ok]

    result, retried = _exec_tick_with_retry(sprites, "spr_x")

    assert retried is False
    assert result is ok
    assert sprites.exec.call_count == 1


def test_exec_tick_with_retry_does_not_retry_busy():
    """A busy skip (exit 75) is not a wedge --- no retry."""
    from slop_salon.cli import _exec_tick_with_retry

    busy = MagicMock(stdout="", stderr="a tick is already running", exit_code=75)
    sprites = MagicMock()
    sprites.exec.side_effect = [busy]

    _, retried = _exec_tick_with_retry(sprites, "spr_x")

    assert retried is False
    assert sprites.exec.call_count == 1


def test_exec_tick_with_retry_genuine_wedge_stays_wedged():
    from slop_salon.cli import _exec_tick_with_retry
    from slop_salon.healing import is_wedge

    sprites = MagicMock()
    sprites.exec.side_effect = [_wedge_result(), _wedge_result()]

    result, retried = _exec_tick_with_retry(sprites, "spr_x")

    assert retried is True
    assert sprites.exec.call_count == 2
    # Second attempt still carries the signature, so the healer still acts.
    assert is_wedge(result)


def test_wake_retries_transient_wedge_and_recovers(live_config):
    """Wedged once then ok: retried, stays green, flagged as retried."""
    ok = MagicMock(stdout="", stderr="", exit_code=0)
    seq = {"spr_lou": [ok], "spr_mina": [_wedge_result(), ok]}

    def _exec(sprite_id, _cmd):
        return seq[sprite_id].pop(0)

    with (
        patch("slop_salon.cli.SpritesClient") as mock_class,
        patch("slop_salon.cli._heal_wedged_agents"),
    ):
        instance = MagicMock()
        instance.exec.side_effect = _exec
        mock_class.return_value = instance

        result = runner.invoke(app, ["wake"])

    assert result.exit_code == 0, result.output  # mina recovered on retry
    assert "retried" in result.output
    assert "fail" not in result.output


def test_wake_genuine_wedge_retried_then_red(live_config):
    """Wedged on both attempts: retried, still fails, reddens the run."""
    ok = MagicMock(stdout="", stderr="", exit_code=0)
    seq = {"spr_lou": [ok], "spr_mina": [_wedge_result(), _wedge_result()]}

    def _exec(sprite_id, _cmd):
        return seq[sprite_id].pop(0)

    with (
        patch("slop_salon.cli.SpritesClient") as mock_class,
        patch("slop_salon.cli._heal_wedged_agents"),
    ):
        instance = MagicMock()
        instance.exec.side_effect = _exec
        mock_class.return_value = instance

        result = runner.invoke(app, ["wake"])

    assert result.exit_code == 1, result.output
    assert "fail(1)" in result.output
    assert "retried" in result.output


def test_drift_reports_clean_and_drift(fake_config, tmp_path):
    # Create a templates dir + SOUL.md alongside the config
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "CLAUDE.md").write_text("You are {{name}} ({{handle}}).\n")
    (templates / "slop-tick").write_text("#!/bin/bash\necho tick\n")
    (tmp_path / "SOUL.md").write_text("immutable constitution\n")

    def fake_fetch(repo: str, files):
        # lou's CLAUDE.md has drifted (extra line); SOUL.md and slop-tick are clean
        if "lou" in repo:
            return {
                "SOUL.md": "immutable constitution\n",
                "CLAUDE.md": "You are lou (lou.slopsalon.art).\nself-added line\n",
                "slop-tick": "#!/bin/bash\necho tick\n",
            }
        # other: everything clean
        return {
            "SOUL.md": "immutable constitution\n",
            "CLAUDE.md": "You are other (other.slopsalon.art).\n",
            "slop-tick": "#!/bin/bash\necho tick\n",
        }

    with patch("slop_salon.cli._fetch_live_files", side_effect=fake_fetch):
        result = runner.invoke(app, ["drift", "lou"])

        assert result.exit_code == 0, result.output
        assert "SOUL.md" in result.output and "clean" in result.output
        assert "CLAUDE.md" in result.output and "drift" in result.output
        assert "+self-added line" in result.output


def test_drift_scans_all_agents_when_no_name(fake_config, tmp_path):
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "CLAUDE.md").write_text("You are {{name}}.\n")
    (templates / "slop-tick").write_text("tick\n")
    (tmp_path / "SOUL.md").write_text("soul\n")

    captured_repos = []

    def fake_fetch(repo, files):
        captured_repos.append(repo)
        return {f: None for f in files}

    with patch("slop_salon.cli._fetch_live_files", side_effect=fake_fetch):
        result = runner.invoke(app, ["drift"])

        assert result.exit_code == 0, result.output
        assert "ANUcybernetics/slop-salon-lou" in captured_repos
        assert "ANUcybernetics/slop-salon-other" in captured_repos


def test_drift_handles_missing_repo_gracefully(fake_config, tmp_path):
    import subprocess as sp

    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "CLAUDE.md").write_text("You are {{name}}.\n")
    (tmp_path / "SOUL.md").write_text("soul\n")

    def fake_fetch(repo, files):
        if "lou" in repo:
            raise sp.CalledProcessError(
                1,
                ["gh", "repo", "clone", repo],
                stderr=b"GraphQL: Could not resolve to a Repository",
            )
        return {f: "soul\n" if f == "SOUL.md" else "You are other.\n" for f in files}

    with patch("slop_salon.cli._fetch_live_files", side_effect=fake_fetch):
        result = runner.invoke(app, ["drift"])

        assert result.exit_code == 0, result.output
        assert "lou" in result.output
        assert "could not fetch" in result.output
        # other should still get processed after lou fails
        assert "other" in result.output
        assert "clean" in result.output


@pytest.fixture
def fake_config_live(tmp_path, monkeypatch):
    cfg = tmp_path / "slop_salon.toml"
    cfg.write_text(
        """
[agents.lou]
handle = "lou.slopsalon.art"
github_repo = "ANUcybernetics/slop-salon-lou"
sprite_id = "spr_lou"
siblings = ["mina"]
live = true

[agents.mina]
handle = "mina.slopsalon.art"
github_repo = "ANUcybernetics/slop-salon-mina"
sprite_id = "spr_mina"
siblings = ["lou"]
live = true
"""
    )
    monkeypatch.chdir(tmp_path)
    return cfg


def _usage_line(agent: str, session: str, mtime: int, **kwargs) -> str:
    """Build one fake `slop-usage tally` JSONL line for the sprite-exec stub."""
    base = {
        "agent": agent,
        "session": session,
        "mtime": mtime,
        "in_new": 50,
        "cache_create": 90_000,
        "cache_read": 900_000,
        "output": 9_000,
        "turns": 30,
        "cost_usd": 0.78,
    }
    base.update(kwargs)
    return json.dumps(base)


def test_usage_aggregates_across_live_agents(fake_config_live):
    import json as _json
    import time as _time

    now = int(_time.time())
    sprite_outputs = {
        "spr_lou": "\n".join(
            [
                _usage_line("lou", "aaaa0001", now - 7200, cost_usd=0.80),
                _usage_line("lou", "aaaa0002", now - 3600, cost_usd=0.85),
                _usage_line("lou", "aaaa0003", now - 600, cost_usd=0.90),
            ]
        ),
        "spr_mina": "\n".join(
            [
                _usage_line("mina", "bbbb0001", now - 7200, cost_usd=0.70),
                _usage_line("mina", "bbbb0002", now - 600, cost_usd=0.75),
            ]
        ),
    }

    def fake_exec(sprite_id, _cmd):
        return MagicMock(stdout=sprite_outputs[sprite_id], stderr="", exit_code=0)

    with patch("slop_salon.cli.SpritesClient") as mock_class:
        instance = MagicMock()
        instance.exec.side_effect = fake_exec
        mock_class.return_value = instance

        from slop_salon.cli import app as _app  # local import to ensure json import side-effects

        result = runner.invoke(_app, ["usage"])

        assert result.exit_code == 0, result.output
        # Header + per-agent rows + total
        assert "agent" in result.output
        assert "lou" in result.output
        assert "mina" in result.output
        # Per-agent totals: lou 0.80+0.85+0.90 = 2.55, mina 0.70+0.75 = 1.45, grand 4.00
        assert "$    2.55" in result.output
        assert "$    1.45" in result.output
        assert "total" in result.output
        assert "$    4.00" in result.output
        _ = _json  # silence unused


def test_usage_single_agent(fake_config_live):
    with patch("slop_salon.cli.SpritesClient") as mock_class:
        instance = MagicMock()
        instance.exec.return_value = MagicMock(
            stdout=_usage_line("lou", "abcd0001", 1_700_000_000, cost_usd=0.50),
            stderr="",
            exit_code=0,
        )
        mock_class.return_value = instance

        result = runner.invoke(app, ["usage", "lou"])

        assert result.exit_code == 0, result.output
        assert "lou" in result.output
        assert "mina" not in result.output
        # Only one sprite-exec call (the named agent)
        assert instance.exec.call_count == 1
        assert instance.exec.call_args[0][0] == "spr_lou"


def test_usage_since_filters_by_mtime(fake_config_live):
    import time as _time

    now = int(_time.time())
    # Three sessions: 3 hours ago, 30 min ago, 5 min ago
    stdout = "\n".join(
        [
            _usage_line("lou", "old00001", now - 10800),
            _usage_line("lou", "mid00001", now - 1800),
            _usage_line("lou", "new00001", now - 300),
        ]
    )

    with patch("slop_salon.cli.SpritesClient") as mock_class:
        instance = MagicMock()
        instance.exec.return_value = MagicMock(stdout=stdout, stderr="", exit_code=0)
        mock_class.return_value = instance

        result = runner.invoke(app, ["usage", "lou", "--since", "1.hour", "--per-tick"])

        assert result.exit_code == 0, result.output
        # Old session should be filtered out by --since 1.hour
        assert "old00001" not in result.output
        assert "mid00001" in result.output
        assert "new00001" in result.output


def test_usage_per_tick_shows_each_session(fake_config_live):
    stdout = "\n".join(
        [
            _usage_line("lou", "sess0001", 1_700_000_000, turns=10, output=500),
            _usage_line("lou", "sess0002", 1_700_000_100, turns=20, output=1000),
        ]
    )

    with patch("slop_salon.cli.SpritesClient") as mock_class:
        instance = MagicMock()
        instance.exec.return_value = MagicMock(stdout=stdout, stderr="", exit_code=0)
        mock_class.return_value = instance

        result = runner.invoke(app, ["usage", "lou", "--per-tick"])

        assert result.exit_code == 0, result.output
        assert "sess0001" in result.output
        assert "sess0002" in result.output
        assert "turns=10" in result.output
        assert "turns=20" in result.output


def test_usage_json_output(fake_config_live):
    stdout = "\n".join(
        [
            _usage_line("lou", "sess0001", 1_700_000_000, cost_usd=0.5),
            _usage_line("lou", "sess0002", 1_700_000_100, cost_usd=1.0),
        ]
    )

    with patch("slop_salon.cli.SpritesClient") as mock_class:
        instance = MagicMock()
        instance.exec.return_value = MagicMock(stdout=stdout, stderr="", exit_code=0)
        mock_class.return_value = instance

        result = runner.invoke(app, ["usage", "lou", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 1
        entry = data[0]
        assert entry["agent"] == "lou"
        assert entry["ticks"] == 2
        assert entry["total_cost_usd"] == 1.5
        assert entry["max_cost_usd"] == 1.0
        # statistics.median of 2 values averages them
        assert entry["median_cost_usd"] == 0.75


def test_usage_reports_sprite_errors(fake_config_live):
    with patch("slop_salon.cli.SpritesClient") as mock_class:
        instance = MagicMock()
        instance.exec.return_value = MagicMock(
            stdout="", stderr="slop-usage: command not found", exit_code=127
        )
        mock_class.return_value = instance

        result = runner.invoke(app, ["usage", "lou"])

        assert result.exit_code == 0, result.output
        assert "ERROR" in result.output
        assert "command not found" in result.output


def test_usage_rejects_unknown_agent(fake_config_live):
    result = runner.invoke(app, ["usage", "ghost"])
    assert result.exit_code != 0
    assert "ghost" in result.output


def test_usage_rejects_malformed_since(fake_config_live):
    with patch("slop_salon.cli.SpritesClient"):
        result = runner.invoke(app, ["usage", "lou", "--since", "yesterday"])
        assert result.exit_code != 0


def test_new_invokes_provisioning(fake_config):
    with patch("slop_salon.cli.provision_agent") as mock_provision:
        result = runner.invoke(app, ["new", "lou", "--yes-dns"])

        assert result.exit_code == 0, result.output
        mock_provision.assert_called_once()
        kwargs = mock_provision.call_args.kwargs or {}
        args = mock_provision.call_args.args
        # Either positional or keyword
        if args:
            assert args[0] == "lou"
        else:
            assert kwargs.get("name") == "lou" or kwargs.get("agent_name") == "lou"
        assert kwargs.get("skip_dns_confirm") is True or "skip_dns_confirm=True" in str(
            mock_provision.call_args
        )


def test_failure_tail_keeps_claude_error_when_stderr_is_noisy():
    """A claude-err tick reports on stdout while git chatters on stderr.

    Regression: `stderr or stdout` printed only the git push output, so the
    reason claude died never reached the log.
    """
    result = ExecResult(
        stdout="API Error: 500 vLLM: too many images in request",
        stderr=(
            "To https://github.com/ANUcybernetics/slop-salon-gert.git\n"
            "   267481a..d99d40b  main -> main"
        ),
        exit_code=0,
    )

    lines = _failure_tail(result)

    assert any("500 vLLM: too many images" in line for line in lines)
    assert any("main -> main" in line for line in lines)


def test_failure_tail_omits_an_empty_stream():
    result = ExecResult(stdout="", stderr="i/o timeout", exit_code=1)

    assert _failure_tail(result) == ["[err] i/o timeout"]
