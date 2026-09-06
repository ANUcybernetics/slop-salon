"""Tests for slop_salon.config."""

from __future__ import annotations

import pytest

from slop_salon.config import Agent, load_config


def test_load_config_returns_agents_by_name(tmp_path):
    cfg = tmp_path / "slop_salon.toml"
    cfg.write_text(
        """
[salons.one]

[agents.lou]
handle = "lou.slopsalon.art"
github_repo = "ANUcybernetics/slop-salon-lou"
sprite_id = "spr_abc123"
salon = "one"

[agents.other]
handle = "other.slopsalon.art"
github_repo = "ANUcybernetics/slop-salon-other"
sprite_id = ""
salon = "one"
"""
    )

    config = load_config(cfg)

    assert "lou" in config.agents
    lou = config.agents["lou"]
    assert isinstance(lou, Agent)
    assert lou.name == "lou"
    assert lou.handle == "lou.slopsalon.art"
    assert lou.github_repo == "ANUcybernetics/slop-salon-lou"
    assert lou.sprite_id == "spr_abc123"
    assert lou.siblings == ["other"]


SALONS = """
default_provider = "fallback"

[providers.fallback]
runner = "claude"

[providers.a-model]
runner = "claude"

[providers.b-model]
runner = "claude"

[salons.a]
label = "Model A"
provider = "a-model"

[salons.b]
provider = "b-model"

[agents.lou]
handle = "lou.slopsalon.art"
github_repo = "o/lou"
salon = "a"

[agents.mina]
handle = "mina.slopsalon.art"
github_repo = "o/mina"
salon = "b"

[agents.gert]
handle = "gert.slopsalon.art"
github_repo = "o/gert"
salon = "a"

[agents.vita]
handle = "vita.slopsalon.art"
github_repo = "o/vita"
salon = "a"
provider = "fallback"

[agents.solo]
handle = "solo.slopsalon.art"
github_repo = "o/solo"
"""


def _salons_config(tmp_path, text=SALONS):
    cfg = tmp_path / "slop_salon.toml"
    cfg.write_text(text)
    return load_config(cfg)


def test_siblings_are_the_rest_of_the_salon_in_registry_order(tmp_path):
    config = _salons_config(tmp_path)

    assert config.agents["lou"].siblings == ["gert", "vita"]
    assert config.agents["gert"].siblings == ["lou", "vita"]
    assert config.agents["mina"].siblings == []
    assert config.agents["solo"].siblings == []
    assert config.members("a") == ["lou", "gert", "vita"]
    assert config.salons["a"].label == "Model A"
    assert config.salons["b"].label == "b"


def test_provider_precedence_is_agent_then_salon_then_default(tmp_path):
    config = _salons_config(tmp_path)

    assert config.provider_for("lou").name == "a-model"
    assert config.provider_for("vita").name == "fallback"
    assert config.provider_for("solo").name == "fallback"


def test_explicit_siblings_list_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="derived from `salon`"):
        _salons_config(tmp_path, SALONS + 'siblings = ["lou"]\n')


def test_undeclared_salon_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="salon 'nope'"):
        _salons_config(tmp_path, SALONS + 'salon = "nope"\n')


def test_salon_provider_must_exist(tmp_path):
    with pytest.raises(ValueError, match="salon 'c'"):
        _salons_config(tmp_path, SALONS + '\n[salons.c]\nprovider = "nope"\n')


def test_registry_salons_are_closed():
    """Every agent in the real registry sits in a salon, and the sibling graph
    never leaves it: an agent's siblings are exactly the rest of its salon, so
    the relation is symmetric and no name crosses a salon boundary. Season 2
    (task-17) rests on this --- one leaked name in one SIBLINGS.md and the
    salons stop being independent."""
    config = load_config("slop_salon.toml")

    assert config.salons, "no [salons.*] blocks in the registry"
    for agent in config.agents.values():
        assert agent.salon, f"{agent.name} is in no salon"
        expected = [m for m in config.members(agent.salon) if m != agent.name]
        assert agent.siblings == expected, agent.name
        for sibling in agent.siblings:
            assert agent.name in config.agents[sibling].siblings, (agent.name, sibling)
    for salon in config.salons.values():
        assert salon.provider, f"salon {salon.name} names no provider"
        assert len(config.members(salon.name)) >= 2, f"salon {salon.name} is not a salon"


def test_load_config_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.toml")


def test_save_sprite_id_updates_file_in_place(tmp_path):
    from slop_salon.config import save_sprite_id

    cfg = tmp_path / "slop_salon.toml"
    cfg.write_text(
        """
[agents.lou]
handle = "lou.slopsalon.art"
github_repo = "ANUcybernetics/slop-salon-lou"
sprite_id = ""
"""
    )

    config = load_config(cfg)
    save_sprite_id(config, "lou", "spr_xyz")

    reloaded = load_config(cfg)
    assert reloaded.agents["lou"].sprite_id == "spr_xyz"


def test_save_sprite_id_appends_when_field_missing(tmp_path):
    """If the agent block lacks a sprite_id line, save_sprite_id should add it."""
    from slop_salon.config import save_sprite_id

    cfg = tmp_path / "slop_salon.toml"
    cfg.write_text(
        """
[agents.lou]
handle = "lou.slopsalon.art"
github_repo = "ANUcybernetics/slop-salon-lou"
"""
    )

    config = load_config(cfg)
    save_sprite_id(config, "lou", "spr_new")

    reloaded = load_config(cfg)
    assert reloaded.agents["lou"].sprite_id == "spr_new"
