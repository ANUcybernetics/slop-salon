"""Tests for slop_studio.tools.bsky CLI commands.

Strategy: each command is a typer app; we invoke via CliRunner and
mock atproto.Client at the import site so no real HTTP happens.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture
def bsky_env(monkeypatch):
    """Set the env vars every bsky-* command needs."""
    monkeypatch.setenv("BSKY_HANDLE", "boden.slopsalon.art")
    monkeypatch.setenv("BSKY_PASSWORD", "test-password")


@pytest.fixture
def mock_atproto_client():
    """Yield a mocked atproto.Client. Patches at the bsky module import path."""
    with patch("slop_studio.tools.bsky.Client") as mock_class:
        instance = MagicMock()
        mock_class.return_value = instance
        yield instance


def test_post_text_only(bsky_env, mock_atproto_client):
    from slop_studio.tools.bsky import post_app

    result = runner.invoke(post_app, ["--text", "hello world"])

    assert result.exit_code == 0
    mock_atproto_client.login.assert_called_once_with("boden.slopsalon.art", "test-password")
    mock_atproto_client.send_post.assert_called_once()
    args, kwargs = mock_atproto_client.send_post.call_args
    assert kwargs.get("text") == "hello world" or (args and args[0] == "hello world")


def test_post_requires_handle_env(monkeypatch, mock_atproto_client):
    monkeypatch.delenv("BSKY_HANDLE", raising=False)
    monkeypatch.setenv("BSKY_PASSWORD", "test-password")

    from slop_studio.tools.bsky import post_app

    result = runner.invoke(post_app, ["--text", "hello"])

    assert result.exit_code != 0
    assert "BSKY_HANDLE" in (result.stderr or result.output)


def test_post_requires_password_env(monkeypatch, mock_atproto_client):
    monkeypatch.setenv("BSKY_HANDLE", "boden.slopsalon.art")
    monkeypatch.delenv("BSKY_PASSWORD", raising=False)

    from slop_studio.tools.bsky import post_app

    result = runner.invoke(post_app, ["--text", "hello"])

    assert result.exit_code != 0
    assert "BSKY_PASSWORD" in (result.stderr or result.output)
