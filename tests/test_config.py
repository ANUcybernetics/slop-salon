"""Tests for the registry loader, plus sanity checks on the real registry."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from slop_salon.config import load_config, save_sprite_id

REAL_REGISTRY = Path(__file__).resolve().parent.parent / "slop_salon.toml"


def test_siblings_are_the_rest_of_the_salon_in_registry_order(registry):
    config = load_config(registry)
    assert config.agents["lou"].siblings == ["mina"]
    assert config.agents["gert"].siblings == ["vita"]


def test_provider_precedence_is_agent_then_salon_then_default(registry):
    text = registry.read_text().replace(
        '[agents.gert]\nhandle = "gert.slopsalon.art"',
        '[agents.gert]\nprovider = "gw"\nhandle = "gert.slopsalon.art"',
    )
    registry.write_text(text)
    config = load_config(registry)
    assert config.provider_for("gert").name == "gw"  # agent override
    assert config.provider_for("vita").name == "direct"  # salon
    assert config.default_provider == "gw"
    assert config.claude_version == "2.1.263"


def test_model_id_drops_the_preset_suffix(registry):
    config = load_config(registry)
    assert config.provider_for("lou").model_id == "z-ai/glm-5.3-flash"
    assert config.provider_for("gert").model_id == "meta/muse-spark-1.3-contributor"
    assert config.providers["direct"].base_url == "https://openrouter.ai/api"


@pytest.mark.parametrize(
    ("snippet", "expected"),
    [
        ('[providers.x]\nmodel = "m"\n', "`base_url` is required"),
        ('[providers.x]\nbase_url = "u"\nmodel = "m"\nauth = "magic"\n', "unknown auth"),
        ('[providers.x]\nbase_url = "u"\nmodel = "m"\nauth = "secret_env"\n', "secret_env"),
        ('[providers.x]\nbase_url = "u"\nmodel = "m"\nsecret_env = "K"\n', "secret_env"),
        ('[salons.s]\nprovider = "nope"\n', "no \\[providers.\\*\\] block"),
        (
            '[agents.a]\nhandle = "h"\ngithub_repo = "r"\nsalon = "nope"\n',
            "no \\[salons.\\*\\] block",
        ),
        (
            '[agents.a]\nhandle = "h"\ngithub_repo = "r"\nsoul = "nope"\n',
            "no \\[souls.\\*\\] block",
        ),
        ('[agents.a]\nhandle = "h"\ngithub_repo = "r"\nsiblings = ["b"]\n', "derived from `salon`"),
        ('default_provider = "nope"\n', "no \\[providers.\\*\\] block"),
    ],
)
def test_registry_errors_are_caught_at_load(tmp_path, snippet, expected):
    cfg = tmp_path / "slop_salon.toml"
    cfg.write_text(snippet)
    with pytest.raises(ValueError, match=expected):
        load_config(cfg)


def test_an_agent_resolving_to_no_provider_says_so(tmp_path):
    cfg = tmp_path / "slop_salon.toml"
    cfg.write_text('[agents.a]\nhandle = "h"\ngithub_repo = "r"\n')
    with pytest.raises(ValueError, match="resolves to no provider"):
        load_config(cfg).provider_for("a")


def test_live_agents_need_a_sprite(registry):
    assert [a.name for a in load_config(registry).live_agents()] == ["lou", "mina", "gert"]


def test_save_sprite_id_updates_file_in_place(registry):
    config = load_config(registry)
    save_sprite_id(config, "vita", "vita")
    assert load_config(registry).agents["vita"].sprite_id == "vita"
    save_sprite_id(config, "lou", "lou-2")
    assert load_config(registry).agents["lou"].sprite_id == "lou-2"


# --- The real registry ---


def test_real_registry_salons_are_closed_and_crossed_with_every_soul():
    """Three salons of three, each carrying one of each soul, so soul and model
    vary independently; and no sibling edge leaves a salon."""
    config = load_config(REAL_REGISTRY)
    for agent in config.agents.values():
        assert agent.salon, f"{agent.name} is in no salon"
        assert agent.soul, f"{agent.name} has no soul"
        for sibling in agent.siblings:
            assert config.agents[sibling].salon == agent.salon
    for salon in config.salons:
        souls = Counter(a.soul for a in config.agents.values() if a.salon == salon)
        assert souls == Counter(config.souls.keys()), f"salon {salon} souls: {dict(souls)}"


def test_real_registry_souls_and_providers_exist():
    config = load_config(REAL_REGISTRY)
    for soul in config.souls:
        assert (REAL_REGISTRY.parent / "souls" / f"{soul}.md").is_file()
    for name in config.agents:
        provider = config.provider_for(name)
        assert provider.auth == "connector"
        assert provider.base_url.startswith("https://api.sprites.dev/v1/gateway/")
    assert config.claude_version
