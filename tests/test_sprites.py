"""Tests for slop_salon.sprites.

Create/get_status hit the REST API (mocked via pytest-httpx). Exec shells
out to the `sprite` CLI, so it's tested by mocking subprocess.run.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pytest_httpx import HTTPXMock

from slop_salon.sprites import SpritesClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SPRITES_API_TOKEN", "test-token")
    return SpritesClient()


def test_create_sprite_returns_name(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        json={
            "id": "sprite-e7567610-d83d-459c-bb82-a19b0978ea2e",
            "name": "lou",
            "status": "cold",
        },
    )

    name = client.create_sprite(name="lou", env_vars={"AGENT_NAME": "lou", "BSKY_HANDLE": "x"})
    assert name == "lou"


def test_exec_shells_out_to_sprite_cli(client):
    with patch("slop_salon.sprites.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="hello", stderr="", returncode=0)

        result = client.exec("lou", ["echo", "hello"])

    assert result.stdout == "hello"
    assert result.exit_code == 0
    args = mock_run.call_args[0][0]
    assert args[:4] == ["sprite", "exec", "-s", "lou"]
    assert args[-2:] == ["echo", "hello"]


def test_exec_propagates_nonzero_exit(client):
    with patch("slop_salon.sprites.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", stderr="boom", returncode=2)

        result = client.exec("lou", ["false"])

    assert result.exit_code == 2
    assert result.stderr == "boom"


def test_get_status(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(method="GET", json={"name": "lou", "status": "running"})

    status = client.get_status("lou")
    assert status == "running"


def test_requires_api_token(monkeypatch):
    monkeypatch.delenv("SPRITES_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="SPRITES_API_TOKEN"):
        SpritesClient()
