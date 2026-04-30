"""Tests for the `slop` admin CLI."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from slop_studio.cli import app

runner = CliRunner()


@pytest.fixture
def fake_config(tmp_path, monkeypatch):
    cfg = tmp_path / "slop_studio.toml"
    cfg.write_text(
        """
[agents.boden]
handle = "boden.slopsalon.art"
github_repo = "ANUcybernetics/slop-studio-boden"
sprite_id = "spr_abc"
siblings = ["other"]

[agents.other]
handle = "other.slopsalon.art"
github_repo = "ANUcybernetics/slop-studio-other"
sprite_id = "spr_xyz"
siblings = ["boden"]
"""
    )
    monkeypatch.chdir(tmp_path)
    return cfg


def test_status_lists_agents(fake_config):
    with patch("slop_studio.cli.SpritesClient") as mock_class:
        instance = MagicMock()
        instance.get_status.return_value = "running"
        mock_class.return_value = instance

        result = runner.invoke(app, ["status"])

        assert result.exit_code == 0, result.output
        assert "boden" in result.output
        assert "other" in result.output
        assert "running" in result.output


def test_logs_runs_command_in_sprite(fake_config):
    with patch("slop_studio.cli.SpritesClient") as mock_class:
        instance = MagicMock()
        instance.exec.return_value = MagicMock(stdout="(transcript)", stderr="", exit_code=0)
        mock_class.return_value = instance

        result = runner.invoke(app, ["logs", "boden"])

        assert result.exit_code == 0, result.output
        assert "transcript" in result.output
        # Should have exec'd against the right sprite
        instance.exec.assert_called_once()
        sprite_id, command = instance.exec.call_args[0]
        assert sprite_id == "spr_abc"


def test_diff_runs_git_in_sprite(fake_config):
    with patch("slop_studio.cli.SpritesClient") as mock_class:
        instance = MagicMock()
        instance.exec.return_value = MagicMock(
            stdout="diff --git a/x b/x\n+hi", stderr="", exit_code=0
        )
        mock_class.return_value = instance

        result = runner.invoke(app, ["diff", "boden", "--since", "1.day"])

        assert result.exit_code == 0, result.output
        assert "+hi" in result.output


def test_feed_all_agents(fake_config):
    with patch("slop_studio.cli.atproto_client_for_feed") as mock_factory:
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
    with patch("slop_studio.cli.atproto_client_for_feed") as mock_factory:
        mock_client = MagicMock()
        mock_client.get_author_feed.return_value = MagicMock(
            feed=[
                MagicMock(
                    post=MagicMock(
                        record=MagicMock(text="boden's post"),
                        indexed_at="2026-04-30T10:00Z",
                    )
                )
            ]
        )
        mock_factory.return_value = mock_client

        result = runner.invoke(app, ["feed", "boden"])

        assert result.exit_code == 0, result.output
        mock_client.get_author_feed.assert_called_once_with(actor="boden.slopsalon.art", limit=10)


def test_pause_clears_crontab(fake_config):
    with patch("slop_studio.cli.SpritesClient") as mock_class:
        instance = MagicMock()
        instance.exec.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_class.return_value = instance

        result = runner.invoke(app, ["pause", "boden"])

        assert result.exit_code == 0, result.output
        # Should have called crontab -r or similar
        cmd = instance.exec.call_args[0][1]
        assert any("crontab" in part for part in cmd)


def test_resume_reinstalls_crontab(fake_config):
    with patch("slop_studio.cli.SpritesClient") as mock_class:
        instance = MagicMock()
        instance.exec.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_class.return_value = instance

        result = runner.invoke(app, ["resume", "boden"])

        assert result.exit_code == 0, result.output
        cmd = instance.exec.call_args[0][1]
        assert any("crontab" in part for part in cmd)


def test_talk_runs_slop_tick_with_prompt(fake_config):
    with patch("slop_studio.cli.SpritesClient") as mock_class:
        instance = MagicMock()
        instance.exec.return_value = MagicMock(stdout="(claude output)", stderr="", exit_code=0)
        mock_class.return_value = instance

        result = runner.invoke(app, ["talk", "boden", "your last three posts felt similar"])

        assert result.exit_code == 0, result.output
        assert "(claude output)" in result.output

        cmd = instance.exec.call_args[0][1]
        # The prompt should appear in the exec command
        joined = " ".join(cmd)
        assert "slop-tick" in joined
        assert "your last three posts felt similar" in joined


def test_new_invokes_provisioning(fake_config):
    with patch("slop_studio.cli.provision_agent") as mock_provision:
        result = runner.invoke(app, ["new", "boden", "--yes-dns"])

        assert result.exit_code == 0, result.output
        mock_provision.assert_called_once()
        kwargs = mock_provision.call_args.kwargs or {}
        args = mock_provision.call_args.args
        # Either positional or keyword
        if args:
            assert args[0] == "boden"
        else:
            assert kwargs.get("name") == "boden" or kwargs.get("agent_name") == "boden"
        assert kwargs.get("skip_dns_confirm") is True or "skip_dns_confirm=True" in str(
            mock_provision.call_args
        )
