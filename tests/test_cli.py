"""Tests for the `slop` admin CLI."""

from __future__ import annotations

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


def test_feed_all_agents(fake_config):
    with patch("slop_salon.cli.atproto_client_for_feed") as mock_factory:
        mock_client = MagicMock()
        mock_client.get_author_feed.return_value = MagicMock(
            feed=[
                MagicMock(
                    post=MagicMock(
                        record=MagicMock(text="a post"),
                        indexed_at="2026-04-30T10:00Z",
                    )
                )
            ]
        )
        mock_factory.return_value = mock_client

        result = runner.invoke(app, ["feed"])

        assert result.exit_code == 0, result.output
        assert "a post" in result.output
        # Called once per agent (2 in fake_config)
        assert mock_client.get_author_feed.call_count == 2


def test_feed_single_agent(fake_config):
    with patch("slop_salon.cli.atproto_client_for_feed") as mock_factory:
        mock_client = MagicMock()
        mock_client.get_author_feed.return_value = MagicMock(
            feed=[
                MagicMock(
                    post=MagicMock(
                        record=MagicMock(text="lou's post"),
                        indexed_at="2026-04-30T10:00Z",
                    )
                )
            ]
        )
        mock_factory.return_value = mock_client

        result = runner.invoke(app, ["feed", "lou"])

        assert result.exit_code == 0, result.output
        mock_client.get_author_feed.assert_called_once_with(actor="lou.slopsalon.art", limit=10)


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
