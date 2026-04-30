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


def test_apt_install_cmd_uses_required_packages():
    from slop_salon.provision import _build_apt_install_cmd

    cmd = _build_apt_install_cmd()
    assert "apt-get update" in cmd
    assert "apt-get install -y" in cmd
    for pkg in ("git", "imagemagick", "ffmpeg", "python3.14"):
        assert pkg in cmd


def test_uv_install_cmd_installs_uv_and_slop_salon():
    from slop_salon.provision import _build_uv_and_slop_install_cmd

    cmd = _build_uv_and_slop_install_cmd()
    assert "astral.sh/uv/install.sh" in cmd
    assert "uv tool install" in cmd
    assert "ANUcybernetics/slop-salon" in cmd


def test_clone_and_symlink_cmd_includes_repo_and_symlink():
    from slop_salon.provision import _build_clone_and_symlink_cmd

    cmd = _build_clone_and_symlink_cmd("boden", "https://x@github.com/y/z.git")
    assert "git clone" in cmd
    assert "~/slop-salon-boden" in cmd
    assert "ln -sf ~/slop-salon-boden/slop-tick ~/.local/bin/slop-tick" in cmd


def test_pre_commit_install_cmd_uses_uv_not_pip():
    from slop_salon.provision import _build_pre_commit_install_cmd

    cmd = _build_pre_commit_install_cmd("boden")
    assert "uv tool install pre-commit" in cmd
    assert "pip install" not in cmd
    assert "pre-commit install" in cmd


def test_git_config_cmd_chmods_credentials():
    from slop_salon.provision import _build_git_config_cmd

    cmd = _build_git_config_cmd("boden", "ghp_secret")
    assert "git config user.name" in cmd
    assert "ghp_secret@github.com" in cmd
    assert "chmod 600 ~/.git-credentials" in cmd


def test_install_crontab_cmd_pipes_text_to_crontab():
    from slop_salon.provision import _build_install_crontab_cmd

    cmd = _build_install_crontab_cmd("AGENT_NAME=boden\n*/30 * * * * tick")
    assert "| crontab -" in cmd
    assert "AGENT_NAME=boden" in cmd


def test_build_template_files_interpolates_placeholders(tmp_path):
    from slop_salon.provision import _build_template_files

    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    (templates_dir / "CLAUDE.md").write_text("Hi {{name}} ({{handle}})")
    (templates_dir / "SIBLINGS.md").write_text("Sibling: {{sibling_name}}")
    soul = tmp_path / "SOUL.md"
    soul.write_text("# Constitution")

    files = _build_template_files(
        templates_dir, soul, "boden", "boden.slopsalon.art", "other", "other.slopsalon.art"
    )

    assert files["SOUL.md"] == "# Constitution"
    assert files["CLAUDE.md"] == "Hi boden (boden.slopsalon.art)"
    assert files["SIBLINGS.md"] == "Sibling: other"


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
