"""Tests for slop_salon.recreate.

Focused on the ordering invariant that makes an unattended self-heal safe: the
destroy at step 1 is irreversible, so anything that can fail on a credential
has to fail before it. A wedged sprite that still exists gets another go on the
next wake; a destroyed one with no clone and no `slop-tick` does not.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

CONFIG = """
default_provider = "test-provider"

[providers.test-provider]
runner = "claude"
env = { ANTHROPIC_BASE_URL = "https://example.invalid" }
secret_env = { ANTHROPIC_API_KEY = "TEST_PROVIDER_TOKEN" }

[agents.mina]
handle = "mina.slopsalon.art"
github_repo = "ANUcybernetics/slop-salon-mina"
sprite_id = "mina"
siblings = ["lou"]
"""


@pytest.fixture
def salon(tmp_path, monkeypatch):
    (tmp_path / "slop_salon.toml").write_text(CONFIG)
    monkeypatch.setenv("TEST_PROVIDER_TOKEN", "not-a-real-token")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _run(env, **verdict_kwargs):
    """Drive `recreate` with a stubbed env and a forced pre-flight verdict."""
    from slop_salon import recreate as recreate_mod
    from slop_salon.provision import AuthkeyVerdict

    sprites = MagicMock()
    sprites.exec.return_value = MagicMock(stdout="", stderr="", exit_code=0)

    with (
        patch.object(recreate_mod, "resolve_secrets", return_value=env),
        patch.object(recreate_mod, "subprocess") as mock_sub,
        patch.object(
            recreate_mod,
            "check_tailscale_authkey",
            return_value=AuthkeyVerdict(**verdict_kwargs),
        ),
    ):
        try:
            recreate_mod.recreate("mina", sprites=sprites)
        except SystemExit as exc:
            return mock_sub, sprites, exc
        return mock_sub, sprites, None


def test_fatal_authkey_aborts_before_the_destroy(salon):
    """The August 2026 failure: an expired key must not cost us the sprite."""
    mock_sub, sprites, exc = _run(
        {"GH_TOKEN": "ghp_x", "TAILSCALE_AUTHKEY": "tskey-auth-dead-key"},
        fatal="auth key expired",
    )

    assert exc is not None
    assert "auth key expired" in str(exc)
    mock_sub.run.assert_not_called()
    sprites.create_sprite.assert_not_called()


def test_warning_authkey_still_recreates(salon, capsys):
    """Cannot-verify is not known-bad --- the heal proceeds, loudly."""
    mock_sub, sprites, exc = _run(
        {"GH_TOKEN": "ghp_x", "TAILSCALE_AUTHKEY": "tskey-auth-live-key"},
        warning="TAILSCALE_API_TOKEN is unset",
    )

    assert exc is None
    mock_sub.run.assert_called_once()
    sprites.create_sprite.assert_called_once()
    assert "TAILSCALE_API_TOKEN is unset" in capsys.readouterr().out
