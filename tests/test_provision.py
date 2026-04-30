"""Tests for slop_salon.provision."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_resolve_secrets_runs_fnox_and_returns_env():
    from slop_salon.provision import resolve_secrets_via_fnox

    fake_env_output = (
        "BSKY_HANDLE=boden.slopsalon.art\nBSKY_PASSWORD=topsecret\nANTHROPIC_API_KEY=sk-ant-xxx\n"
    )

    with patch("slop_salon.provision.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=fake_env_output, returncode=0)

        env = resolve_secrets_via_fnox("boden")

    assert env["BSKY_HANDLE"] == "boden.slopsalon.art"
    assert env["BSKY_PASSWORD"] == "topsecret"
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-xxx"

    # Verify it called fnox correctly
    args = mock_run.call_args[0][0]
    assert args[0:3] == ["fnox", "exec", "--profile"]
    assert args[3] == "boden"


def test_resolve_secrets_raises_on_fnox_failure():
    from slop_salon.provision import resolve_secrets_via_fnox

    with patch("slop_salon.provision.subprocess.run") as mock_run:
        mock_run.side_effect = Exception("fnox: profile not found")

        with pytest.raises(Exception, match="fnox"):
            resolve_secrets_via_fnox("nonexistent")


def test_provision_calls_steps_in_order(tmp_path, monkeypatch):
    """The provisioner orchestrates 13 steps; verify the key external calls."""
    from slop_salon import provision

    # Set up a templates dir and config
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    (templates_dir / "CLAUDE.md").write_text("# {{name}} ({{handle}})")
    (templates_dir / "SIBLINGS.md").write_text("# Siblings of {{name}}")
    (templates_dir / "README.md").write_text("# {{name}}")
    (templates_dir / ".gitignore").write_text(".claude/\n")
    (templates_dir / ".pre-commit-config.yaml").write_text("repos: []\n")
    (templates_dir / "slop-tick").write_text("#!/bin/bash\n")
    (templates_dir / "crontab").write_text("*/30 * * * * slop-tick tick\n")

    soul = tmp_path / "SOUL.md"
    soul.write_text("# Soul")

    cfg = tmp_path / "slop_salon.toml"
    cfg.write_text(
        """
[agents.boden]
handle = "boden.slopsalon.art"
github_repo = "ANUcybernetics/slop-salon-boden"
sprite_id = ""
siblings = ["other"]
"""
    )

    monkeypatch.chdir(tmp_path)

    fake_secrets = {
        "BSKY_HANDLE": "boden.slopsalon.art",
        "BSKY_PASSWORD": "x",
        "REPLICATE_API_TOKEN": "y",
        "ANTHROPIC_API_KEY": "z",
        "GH_TOKEN": "ghp_xxx",
    }

    with (
        patch.object(provision, "resolve_secrets_via_fnox", return_value=fake_secrets),
        patch.object(provision, "SpritesClient") as mock_sprites_class,
        patch.object(provision, "subprocess") as mock_sub,
    ):
        sprites = MagicMock()
        sprites.create_sprite.return_value = "spr_new123"
        sprites.exec.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_sprites_class.return_value = sprites
        mock_sub.run.return_value = MagicMock(stdout="", returncode=0)

        provision.provision_agent("boden", skip_dns_confirm=True)

    # 1. gh repo create was called
    gh_calls = [c for c in mock_sub.run.call_args_list if "gh" in c[0][0][0]]
    assert any("repo" in c[0][0] and "create" in c[0][0] for c in gh_calls)

    # 4. Sprite was created
    sprites.create_sprite.assert_called_once()

    # 5-12. Several exec calls happened (apt, claude install, uv tool install, etc.)
    assert sprites.exec.call_count >= 5

    # 13. slop_salon.toml was updated with the sprite ID
    from slop_salon.config import load_config

    reloaded = load_config(cfg)
    assert reloaded.agents["boden"].sprite_id == "spr_new123"
