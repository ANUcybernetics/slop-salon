"""Tests for slop_studio.config."""

from __future__ import annotations

import pytest

from slop_studio.config import Agent, load_config


def test_load_config_returns_agents_by_name(tmp_path):
    cfg = tmp_path / "slop_studio.toml"
    cfg.write_text(
        """
[agents.boden]
handle = "boden.slopsalon.art"
github_repo = "ANUcybernetics/slop-studio-boden"
sprite_id = "spr_abc123"
siblings = ["other"]

[agents.other]
handle = "other.slopsalon.art"
github_repo = "ANUcybernetics/slop-studio-other"
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
    assert boden.github_repo == "ANUcybernetics/slop-studio-boden"
    assert boden.sprite_id == "spr_abc123"
    assert boden.siblings == ["other"]


def test_load_config_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.toml")


def test_save_sprite_id_updates_file_in_place(tmp_path):
    from slop_studio.config import save_sprite_id

    cfg = tmp_path / "slop_studio.toml"
    cfg.write_text(
        """
[agents.boden]
handle = "boden.slopsalon.art"
github_repo = "ANUcybernetics/slop-studio-boden"
sprite_id = ""
siblings = []
"""
    )

    config = load_config(cfg)
    save_sprite_id(config, "boden", "spr_xyz")

    reloaded = load_config(cfg)
    assert reloaded.agents["boden"].sprite_id == "spr_xyz"
