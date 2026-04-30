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
