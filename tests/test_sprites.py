"""Tests for slop_salon.sprites: REST calls are mocked with pytest-httpx, exec
shells out to the `sprite` CLI so subprocess.run is mocked."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from pytest_httpx import HTTPXMock

from slop_salon import sprites
from slop_salon.sprites import SpritesClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SPRITES_API_TOKEN", "test-token")
    return SpritesClient()


def test_create_sprite_sends_labels_and_returns_name(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(method="POST", json={"name": "lou", "status": "cold"})
    assert client.create_sprite("lou", labels=["slop", "salon=one"]) == "lou"
    body = json.loads(httpx_mock.get_requests()[0].content)
    assert body == {"name": "lou", "labels": ["slop", "salon=one"]}


def test_set_labels_and_policy_hit_their_endpoints(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(method="PUT", url="https://api.sprites.dev/v1/sprites/lou", json={})
    httpx_mock.add_response(
        method="POST", url="https://api.sprites.dev/v1/sprites/lou/policy/network", json={}
    )
    client.set_labels("lou", ["slop"])
    client.set_network_policy("lou", [{"include": "defaults"}])
    put, post = httpx_mock.get_requests()
    assert json.loads(put.content) == {"labels": ["slop"]}
    assert json.loads(post.content) == {"rules": [{"include": "defaults"}]}


def test_destroy_tolerates_an_already_missing_sprite(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(method="DELETE", status_code=404)
    client.destroy_sprite("lou")


def test_exec_passes_env_through_the_cli_flag(client):
    with (
        patch("slop_salon.sprites._exec_flags", return_value=[]),
        patch("slop_salon.sprites.subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(stdout="hello", stderr="", returncode=0)
        result = client.exec("lou", ["echo", "hello"], env={"A": "1", "B": "x=y"})
    assert result.stdout == "hello" and result.exit_code == 0
    args = mock_run.call_args[0][0]
    assert args == ["sprite", "exec", "-s", "lou", "--env", "A=1,B=x=y", "--", "echo", "hello"]


def test_exec_drops_port_forwarding_when_the_cli_offers_the_flag():
    """Probed from `--help`, so an older CLI is not handed an unknown flag."""
    sprites._exec_flags.cache_clear()
    with patch("slop_salon.sprites.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout="  --no-port-forward   Disable", stderr="", returncode=0
        )
        assert sprites._exec_flags() == ["--no-port-forward"]
    sprites._exec_flags.cache_clear()
    with patch("slop_salon.sprites.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="  --env <vars>", stderr="", returncode=0)
        assert sprites._exec_flags() == []
    sprites._exec_flags.cache_clear()


def test_exec_refuses_a_value_with_a_comma(client):
    with pytest.raises(ValueError, match="comma"):
        client.exec("lou", ["true"], env={"A": "x,y"})


def test_exec_propagates_nonzero_exit(client):
    with patch("slop_salon.sprites.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", stderr="boom", returncode=2)
        result = client.exec("lou", ["false"])
    assert result.exit_code == 2 and result.stderr == "boom"


def test_requires_api_token(monkeypatch):
    monkeypatch.delenv("SPRITES_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="SPRITES_API_TOKEN"):
        SpritesClient()
