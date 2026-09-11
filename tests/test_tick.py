"""The environment a tick runs in is assembled admin-side, per agent, per tick."""

from __future__ import annotations

import pytest

from slop_salon.config import load_config
from slop_salon.tick import CONNECTOR_PLACEHOLDER_TOKEN, tick_env


def test_connector_provider_sends_a_placeholder_token(registry):
    config = load_config(registry)
    env = tick_env(config, config.agents["lou"])
    assert env["ANTHROPIC_BASE_URL"] == "https://api.sprites.dev/v1/gateway/openrouter/conn1"
    assert env["ANTHROPIC_AUTH_TOKEN"] == CONNECTOR_PLACEHOLDER_TOKEN
    assert env["ANTHROPIC_API_KEY"] == ""
    assert env["ANTHROPIC_MODEL"] == "z-ai/glm-5.3-flash@preset/slop-glm-flash"
    assert env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "1000000"


def test_secret_env_provider_passes_the_admin_secret(registry):
    config = load_config(registry)
    env = tick_env(config, config.agents["gert"])
    assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-or-test"
    assert "CLAUDE_CODE_MAX_CONTEXT_TOKENS" not in env


def test_identity_secrets_and_salon_ride_along(registry):
    config = load_config(registry)
    env = tick_env(config, config.agents["lou"])
    assert env["AGENT_NAME"] == "lou"
    assert env["BSKY_HANDLE"] == "lou.slopsalon.art"
    assert env["BSKY_PASSWORD"] == "lou-pw"
    assert env["GH_TOKEN"] == "ghp_test"
    assert env["REPLICATE_API_TOKEN"] == "r8_test"
    assert env["SLOP_MODEL"] == "z-ai/glm-5.3-flash"
    assert env["SLOP_SALON"] == "one"
    assert env["SLOP_SIBLINGS"] == "mina.slopsalon.art"
    assert env["SLOP_COLLECTIVE"].split() == [
        "lou.slopsalon.art",
        "mina.slopsalon.art",
        "gert.slopsalon.art",
        "vita.slopsalon.art",
    ]


def test_no_value_carries_a_comma(registry):
    """`sprite exec --env` is comma-delimited."""
    config = load_config(registry)
    for agent in config.agents.values():
        assert not any("," in v for v in tick_env(config, agent).values())


@pytest.mark.parametrize(
    "missing", ["SLOP_GH_TOKEN", "SLOP_REPLICATE_API_TOKEN", "TEST_OPENROUTER_KEY"]
)
def test_a_missing_admin_secret_fails_on_the_admin_box(registry, monkeypatch, missing):
    monkeypatch.delenv(missing)
    config = load_config(registry)
    with pytest.raises(RuntimeError, match=missing):
        tick_env(config, config.agents["gert"])


def test_a_missing_bluesky_password_is_named(registry):
    (registry.parent / "secrets.toml").write_text("[agents.lou]\nbsky_password = ''\n")
    config = load_config(registry)
    with pytest.raises(RuntimeError, match="bsky_password for 'lou'"):
        tick_env(config, config.agents["lou"])


def test_credentials_auth_is_declared_but_not_built(registry):
    text = registry.read_text().replace('auth = "connector"', 'auth = "credentials"')
    registry.write_text(text)
    config = load_config(registry)
    with pytest.raises(NotImplementedError):
        tick_env(config, config.agents["lou"])
