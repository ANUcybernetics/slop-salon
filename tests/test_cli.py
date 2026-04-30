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
