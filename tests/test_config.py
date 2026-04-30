"""Tests for slop_salon.config."""

from __future__ import annotations

import pytest

from slop_salon.config import Agent, load_config


def test_load_config_returns_agents_by_name(tmp_path):
    cfg = tmp_path / "slop_salon.toml"
    cfg.write_text(
        """
[agents.boden]
handle = "boden.slopsalon.art"
github_repo = "ANUcybernetics/slop-salon-boden"
sprite_id = "spr_abc123"
siblings = ["other"]

[agents.other]
handle = "other.slopsalon.art"
github_repo = "ANUcybernetics/slop-salon-other"
sprite_id = ""
siblings = ["boden"]
"""
    )

    config = load_config(cfg)

    assert "boden" in config.agents
    boden = config.agents["boden"]
    assert isinstance(boden, Agent)
    assert boden.name == "boden"
    assert boden.handle == "boden.slopsalon.art"
    assert boden.github_repo == "ANUcybernetics/slop-salon-boden"
    assert boden.sprite_id == "spr_abc123"
    assert boden.siblings == ["other"]


def test_load_config_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.toml")


def test_save_sprite_id_updates_file_in_place(tmp_path):
    from slop_salon.config import save_sprite_id

    cfg = tmp_path / "slop_salon.toml"
    cfg.write_text(
        """
[agents.boden]
handle = "boden.slopsalon.art"
github_repo = "ANUcybernetics/slop-salon-boden"
sprite_id = ""
siblings = []
"""
    )

    config = load_config(cfg)
    save_sprite_id(config, "boden", "spr_xyz")

    reloaded = load_config(cfg)
    assert reloaded.agents["boden"].sprite_id == "spr_xyz"
