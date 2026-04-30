"""Tests for slop_salon.sprites (sprites.dev REST client).

Mocks HTTP via pytest-httpx; the test asserts the *shape* of requests
the client makes, decoupled from the exact endpoint paths/auth which
the implementer fills in from sprites.dev docs.
"""

from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from slop_salon.sprites import SpritesClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SPRITES_API_TOKEN", "test-token")
    return SpritesClient()


def test_create_sprite_returns_id(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        json={"id": "spr_abc123", "status": "starting"},
    )

    sprite_id = client.create_sprite(
        name="boden", env_vars={"AGENT_NAME": "boden", "BSKY_HANDLE": "x"}
    )
    assert sprite_id == "spr_abc123"


def test_exec_returns_stdout(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        json={"stdout": "hello", "stderr": "", "exit_code": 0},
    )

    result = client.exec("spr_abc123", ["echo", "hello"])
    assert result.stdout == "hello"
    assert result.exit_code == 0


def test_exec_propagates_nonzero_exit(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        json={"stdout": "", "stderr": "boom", "exit_code": 2},
    )

    result = client.exec("spr_abc123", ["false"])
    assert result.exit_code == 2
    assert result.stderr == "boom"


def test_get_status(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(method="GET", json={"id": "spr_abc123", "status": "running"})

    status = client.get_status("spr_abc123")
    assert status == "running"


def test_requires_api_token(monkeypatch):
    monkeypatch.delenv("SPRITES_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="SPRITES_API_TOKEN"):
        SpritesClient()
