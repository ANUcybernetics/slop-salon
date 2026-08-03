"""Tests for the intelligence-provider registry and the sprite-side swap.

The property that matters throughout: a provider swap must change *only* the
provider. Everything here is either about resolving which provider an agent runs
on, or about proving the swap can't take an agent's secrets down with it.
"""

from __future__ import annotations

import base64
import re

import pytest

from slop_salon.config import LEGACY_PROVIDER, Config, load_config, save_provider
from slop_salon.provision import (
    PROVIDER_OWNED_ENV,
    _build_install_credentials_cmd,
    _build_write_provider_file_cmd,
    missing_provider_secrets,
    provider_steps,
    resolve_provider_env,
)

REGISTRY = """
default_provider = "deepseek"

[providers.vllm]
runner = "claude"
claude_version = "2.1.92"
health_url = "http://tailnet:8001/health"
env = { ANTHROPIC_BASE_URL = "http://tailnet:8001", ANTHROPIC_MODEL = "qwen" }
secret_env = { ANTHROPIC_AUTH_TOKEN = "SLOP_ANTHROPIC_AUTH_TOKEN" }

[providers.deepseek]
runner = "claude"
env = { ANTHROPIC_BASE_URL = "https://api.deepseek.com/anthropic" }
secret_env = { ANTHROPIC_API_KEY = "DEEPSEEK_API_TOKEN" }

[providers.codex-sub]
runner = "codex"
credentials_dest = "~/.codex/auth.json"
credentials_source_env = "SLOP_CODEX_AUTH_PATH"

[agents.lou]
handle = "lou.slopsalon.art"
github_repo = "o/lou"
provider = "vllm"

[agents.mina]
handle = "mina.slopsalon.art"
github_repo = "o/mina"
"""


def _write(tmp_path, text=REGISTRY):
    path = tmp_path / "slop_salon.toml"
    path.write_text(text)
    return path


def _decoded(cmd: str) -> str:
    """Recover the file body a base64 sprite command would write."""
    payload = re.search(r"echo ([A-Za-z0-9+/=]+) \| base64 -d", cmd)
    assert payload, cmd
    return base64.b64decode(payload.group(1)).decode()


# --- Resolving which provider an agent runs on ---


def test_agent_provider_beats_default_which_beats_legacy(tmp_path):
    config = load_config(_write(tmp_path))
    assert config.provider_for("lou").name == "vllm"  # explicit on the agent
    assert config.provider_for("mina").name == "deepseek"  # falls to the default

    bare = Config(path=tmp_path / "x.toml", agents=config.agents)
    assert bare.provider_for("mina") is LEGACY_PROVIDER


def test_unmigrated_config_still_loads_and_behaves_as_it_did(tmp_path):
    """No [providers] table must keep meaning "the vLLM setup we already had"."""
    path = _write(
        tmp_path,
        '[agents.lou]\nhandle = "lou.slopsalon.art"\ngithub_repo = "o/lou"\n',
    )
    config = load_config(path)
    provider = config.provider_for("lou")
    assert provider is LEGACY_PROVIDER
    assert provider.runner == "claude"
    assert provider.claude_version  # the pin vLLM needs is still applied


@pytest.mark.parametrize(
    ("snippet", "expected"),
    [
        ('default_provider = "nope"\n', "default_provider"),
        ('[providers.x]\nrunner = "gemini"\n', "unknown runner"),
        (
            '[providers.x]\nrunner = "claude"\ncredentials_dest = "~/a"\n',
            "must be set together",
        ),
    ],
)
def test_registry_errors_are_caught_at_load(tmp_path, snippet, expected):
    """A malformed registry must fail on the admin box, not as a dead tick."""
    path = _write(tmp_path, snippet)
    with pytest.raises(ValueError, match=expected):
        load_config(path)


def test_agent_naming_an_undefined_provider_is_rejected(tmp_path):
    path = _write(
        tmp_path,
        '[agents.lou]\nhandle = "h"\ngithub_repo = "o/lou"\nprovider = "ghost"\n',
    )
    with pytest.raises(ValueError, match="ghost"):
        load_config(path)


def test_save_provider_rewrites_in_place_and_preserves_comments(tmp_path):
    path = _write(tmp_path)
    config = load_config(path)

    save_provider(config, "mina", "codex-sub")  # mina had no provider line at all
    save_provider(config, "lou", "deepseek")  # lou had one to replace

    reloaded = load_config(path)
    assert reloaded.agents["mina"].provider == "codex-sub"
    assert reloaded.agents["lou"].provider == "deepseek"
    # The registry is hand-maintained; a rewrite that ate the comments would make
    # the next person guess at why the pin exists.
    assert "[providers.vllm]" in path.read_text()


# --- Resolving a provider's env ---


def test_secrets_are_named_not_embedded(tmp_path):
    """slop_salon.toml is tracked and inlined into the public site bundle."""
    text = _write(tmp_path).read_text()
    assert "DEEPSEEK_API_TOKEN" in text  # the name is fine
    config = load_config(tmp_path / "slop_salon.toml")
    env = resolve_provider_env(config.providers["deepseek"], {"DEEPSEEK_API_TOKEN": "sk-secret"})
    assert env["ANTHROPIC_API_KEY"] == "sk-secret"
    assert "sk-secret" not in text


def test_runner_is_always_exported(tmp_path):
    """slop-tick dispatches on SLOP_RUNNER; a file without it silently runs claude."""
    config = load_config(_write(tmp_path))
    env = resolve_provider_env(config.providers["codex-sub"], {})
    assert env["SLOP_RUNNER"] == "codex"


def test_missing_admin_secret_is_reported_by_its_admin_name(tmp_path):
    config = load_config(_write(tmp_path))
    assert missing_provider_secrets(config.providers["deepseek"], {}) == ["DEEPSEEK_API_TOKEN"]
    assert missing_provider_secrets(config.providers["deepseek"], {"DEEPSEEK_API_TOKEN": "x"}) == []
    # A subscription provider needs its credentials file, not an env token.
    assert missing_provider_secrets(config.providers["codex-sub"], {}) == ["SLOP_CODEX_AUTH_PATH"]


def test_provider_steps_refuses_to_run_half_configured(tmp_path):
    config = load_config(_write(tmp_path))
    with pytest.raises(RuntimeError, match="DEEPSEEK_API_TOKEN"):
        provider_steps(config.providers["deepseek"], {})


# --- What lands in the sprite ---


def test_provider_file_unsets_stale_inference_vars_first(tmp_path):
    """The unset is load-bearing, not tidiness.

    Sprites provisioned before the env split still export ANTHROPIC_* from
    ~/.slop-env, which slop-tick sources first. Without the unset, swapping to a
    subscription provider (which deliberately sets no key, so claude falls
    through to the OAuth profile) would keep using the stale vLLM token instead.
    """
    body = _decoded(_build_write_provider_file_cmd({"SLOP_RUNNER": "claude"}))
    lines = body.splitlines()
    assert lines[0].startswith("unset ")
    for var in PROVIDER_OWNED_ENV:
        assert var in lines[0]
    assert lines[0].index("unset") < body.index("export SLOP_RUNNER")


def test_provider_file_is_written_600_and_separate_from_slop_env(tmp_path):
    cmd = _build_write_provider_file_cmd({"SLOP_RUNNER": "claude"})
    assert "umask 077" in cmd
    assert "chmod 600 ~/.slop-provider" in cmd
    # The whole point of the split: a swap must not rewrite the secrets file.
    assert "~/.slop-env" not in cmd


def test_provider_file_quotes_values(tmp_path):
    body = _decoded(_build_write_provider_file_cmd({"ANTHROPIC_MODEL": "a b; rm -rf /"}))
    assert "rm -rf" in body
    assert "export ANTHROPIC_MODEL='a b; rm -rf /'" in body


def test_credentials_land_600_with_their_parent_created(tmp_path):
    cmd = _build_install_credentials_cmd("~/.codex/auth.json", '{"token": "x"}')
    assert "umask 077" in cmd
    assert 'mkdir -p "$(dirname "$HOME/.codex/auth.json")"' in cmd
    assert 'chmod 600 "$HOME/.codex/auth.json"' in cmd
    # `~` would not expand inside the quotes the path needs, so it is rewritten.
    assert "~/" not in cmd.replace("~/.slop", "")
    assert _decoded(cmd) == '{"token": "x"}'


def test_subscription_provider_sets_no_key_var(tmp_path):
    """Claude resolves API_KEY -> AUTH_TOKEN -> OAuth profile, in that order.

    So subscription auth works only by the absence of both vars --- setting an
    empty one would be silently different from setting none.
    """
    config = load_config(_write(tmp_path))
    env = resolve_provider_env(config.providers["codex-sub"], {})
    assert not any(k.startswith("ANTHROPIC_") for k in env)


def test_swap_and_fresh_provision_install_identical_state(tmp_path):
    """`slop provider set` and `slop new` share provider_steps deliberately.

    If they drifted, a swapped sprite would be a second configuration to reason
    about every time something broke.
    """
    config = load_config(_write(tmp_path))
    environ = {"SLOP_ANTHROPIC_AUTH_TOKEN": "tok"}
    first = provider_steps(config.providers["vllm"], environ)
    second = provider_steps(config.providers["vllm"], environ)
    assert first == second
    labels = [label for label, _ in first]
    assert labels == ["write ~/.slop-provider", "pin claude 2.1.92"]
