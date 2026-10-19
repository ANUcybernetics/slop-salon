"""The environment a tick runs in is assembled admin-side, per agent, per tick."""

from __future__ import annotations

import base64
import os
import subprocess

import pytest

from slop_salon.config import load_config
from slop_salon.tick import (
    CONNECTOR_PLACEHOLDER_TOKEN,
    TOOL_DATA_LIMIT_KB,
    session_id,
    tick_command,
    tick_env,
    tick_output,
)
from tests.conftest import use_provider


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


def test_connector_ticks_run_claude_under_the_api_profile(registry):
    env = tick_env(load_config(registry), load_config(registry).agents["lou"])
    assert env["SLOP_RUNNER"] == "claude"
    assert env["AGENT_PROFILE"] == "claude-api"
    assert env["AGENT_MODEL"] == "z-ai/glm-5.3-flash@preset/slop-glm-flash"


def test_a_claude_subscription_passes_the_oauth_token_and_no_endpoint(registry):
    use_provider(registry, "one", "haiku")
    config = load_config(registry)
    env = tick_env(config, config.agents["lou"])
    assert env["SLOP_RUNNER"] == "claude"
    assert env["AGENT_PROFILE"] == "claude-sub"
    assert env["AGENT_MODEL"] == "claude-haiku-5-5"
    assert env["SLOP_MODEL"] == "claude-haiku-5-5"
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat-test"
    assert not any(k.startswith("ANTHROPIC_") for k in env)


def test_a_codex_subscription_passes_the_login_file_comma_free(registry):
    use_provider(registry, "two", "luna")
    config = load_config(registry)
    env = tick_env(config, config.agents["gert"])
    assert env["SLOP_RUNNER"] == "codex"
    assert env["AGENT_PROFILE"] == "codex-sub"
    assert env["AGENT_MODEL"] == "gpt-6-luna"
    assert (
        base64.b64decode(env["SLOP_CODEX_AUTH"])
        == (registry.parent / "codex-auth.json").read_bytes()
    )
    assert not any("," in v for v in env.values())
    assert not any(k.startswith("ANTHROPIC_") for k in env)


@pytest.mark.parametrize(
    ("salon", "provider", "agent", "missing"),
    [
        ("one", "haiku", "lou", "SLOP_CLAUDE_OAUTH_TOKEN"),
        ("two", "luna", "gert", "SLOP_CODEX_AUTH_PATH"),
    ],
)
def test_a_missing_subscription_credential_is_named(
    registry, monkeypatch, salon, provider, agent, missing
):
    use_provider(registry, salon, provider)
    monkeypatch.delenv(missing)
    config = load_config(registry)
    with pytest.raises(RuntimeError, match=missing):
        tick_env(config, config.agents[agent])


def test_the_tick_shell_reports_its_own_pid_as_the_session_id(tmp_path):
    # The platform's session id is the pid of the shell `sprite exec` starts,
    # so `$$` has to reach that shell unexpanded and be expanded there.
    fake = tmp_path / "slop-tick"
    fake.write_text('#!/bin/sh\necho "ticked $1"\n')
    fake.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    shell = subprocess.Popen(tick_command("tick"), stdout=subprocess.PIPE, text=True, env=env)
    stdout, _ = shell.communicate()
    assert session_id(stdout) == str(shell.pid)
    assert tick_output(stdout) == "ticked tick"


def test_the_tick_runs_every_tool_command_under_the_memory_cap(tmp_path):
    # Stands in for claude: runs one tool command the way Claude Code does
    # when CLAUDE_CODE_SHELL_PREFIX is set, the whole command as one argument.
    fake = tmp_path / "slop-tick"
    fake.write_text('#!/bin/sh\n"$CLAUDE_CODE_SHELL_PREFIX" "ulimit -d; echo tool ran"\n')
    fake.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    result = subprocess.run(tick_command("tick"), capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    assert tick_output(result.stdout) == f"{TOOL_DATA_LIMIT_KB}\ntool ran"


def test_no_session_id_without_the_marker():
    assert session_id("Error: connection closed") is None
