"""Tests for the `slop` admin CLI."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from slop_salon.cli import app

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


def test_logs_runs_command_in_sprite(fake_config):
    with patch("slop_salon.cli.SpritesClient") as mock_class:
        instance = MagicMock()
        instance.exec.return_value = MagicMock(stdout="(transcript)", stderr="", exit_code=0)
        mock_class.return_value = instance

        result = runner.invoke(app, ["logs", "lou"])

        assert result.exit_code == 0, result.output
        assert "transcript" in result.output
        # Should have exec'd against the right sprite
        instance.exec.assert_called_once()
        sprite_id, command = instance.exec.call_args[0]
        assert sprite_id == "spr_abc"


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
