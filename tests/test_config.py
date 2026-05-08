"""Tests for slop_salon.config."""

from __future__ import annotations

import pytest

from slop_salon.config import Agent, load_config


def test_load_config_returns_agents_by_name(tmp_path):
    cfg = tmp_path / "slop_salon.toml"
    cfg.write_text(
        """
[agents.lou]
handle = "lou.slopsalon.art"
github_repo = "ANUcybernetics/slop-salon-lou"
sprite_id = "spr_abc123"
siblings = ["other"]

[agents.other]
handle = "other.slopsalon.art"
github_repo = "ANUcybernetics/slop-salon-other"
sprite_id = ""
siblings = ["lou"]
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
siblings = []
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
siblings = []
"""
    )

    config = load_config(cfg)
    save_sprite_id(config, "lou", "spr_new")

    reloaded = load_config(cfg)
    assert reloaded.agents["lou"].sprite_id == "spr_new"
