"""Tests for slop_salon.provision."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_resolve_secrets_runs_fnox_and_returns_env():
    from slop_salon.provision import resolve_secrets_via_fnox

    fake_env_output = (
        "BSKY_HANDLE=lou.slopsalon.art\nBSKY_PASSWORD=topsecret\nANTHROPIC_API_KEY=sk-ant-xxx\n"
    )

    with patch("slop_salon.provision.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=fake_env_output, returncode=0)

        env = resolve_secrets_via_fnox("lou")

    assert env["BSKY_HANDLE"] == "lou.slopsalon.art"
    assert env["BSKY_PASSWORD"] == "topsecret"
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-xxx"

    # Verify it called fnox correctly
    args = mock_run.call_args[0][0]
    assert args[0:3] == ["fnox", "exec", "--profile"]
    assert args[3] == "lou"


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
    # Only media tooling missing from the default sprite image.
    for pkg in ("imagemagick", "ffmpeg", "sox"):
        assert pkg in cmd
    # These ship with the sprite — provisioning must not reinstall them.
    for pkg in ("git", "curl", "jq", "nodejs", "python3.14"):
        assert pkg not in cmd


def test_uv_install_cmd_installs_uv_and_slop_salon():
    from slop_salon.provision import _build_uv_and_slop_install_cmd

    cmd = _build_uv_and_slop_install_cmd()
    assert "astral.sh/uv/install.sh" in cmd
    assert "uv tool install" in cmd
    assert "ANUcybernetics/slop-salon" in cmd


def test_clone_and_symlink_cmd_includes_repo_and_symlinks():
    from slop_salon.provision import _build_clone_and_symlink_cmd

    cmd = _build_clone_and_symlink_cmd("lou", "https://x@github.com/y/z.git")
    assert "git clone" in cmd
    assert "~/slop-salon-lou" in cmd
    assert "ln -sf ~/slop-salon-lou/slop-tick ~/.local/bin/slop-tick" in cmd
    assert "ln -sf ~/slop-salon-lou/slop-tick-loop ~/.local/bin/slop-tick-loop" in cmd


def test_pre_commit_install_cmd_uses_uv_not_pip():
    from slop_salon.provision import _build_pre_commit_install_cmd

    cmd = _build_pre_commit_install_cmd("lou")
    assert "uv tool install pre-commit" in cmd
    assert "pip install" not in cmd
    assert "pre-commit install" in cmd


def test_git_config_cmd_chmods_credentials():
    from slop_salon.provision import _build_git_config_cmd

    cmd = _build_git_config_cmd("lou", "ghp_secret")
    assert "git config user.name" in cmd
    assert "ghp_secret@github.com" in cmd
    assert "chmod 600 ~/.git-credentials" in cmd


def test_create_tick_service_cmd_uses_sprite_env():
    from slop_salon.provision import _build_create_tick_service_cmd

    cmd = _build_create_tick_service_cmd()
    assert "sprite-env services create" in cmd
    assert "tick" in cmd
    assert "slop-tick-loop" in cmd


def test_write_env_file_cmd_encodes_safely_and_chmods_600():
    import base64

    from slop_salon.provision import _build_write_env_file_cmd

    cmd = _build_write_env_file_cmd(
        {
            "AGENT_NAME": "lou",
            "BSKY_PASSWORD": "tricky pwd with $dollar and 'quote'",
            "GH_TOKEN": "ghp_simple",
        }
    )
    # Mode 600 and the canonical filename.
    assert "chmod 600 ~/.slop-env" in cmd
    assert "umask 077" in cmd
    # The body is base64-encoded; decode it and check it round-trips.
    encoded = cmd.split("echo ", 1)[1].split(" ", 1)[0]
    decoded = base64.b64decode(encoded).decode()
    assert "export AGENT_NAME=lou" in decoded
    assert "export GH_TOKEN=ghp_simple" in decoded
    # Tricky chars survive via shlex quoting.
    assert "BSKY_PASSWORD=" in decoded
    assert "$dollar" in decoded
    assert "'quote'" in decoded or "quote" in decoded


def test_build_template_files_interpolates_placeholders(tmp_path):
    from slop_salon.provision import _build_template_files

    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    (templates_dir / "CLAUDE.md").write_text("Hi {{name}} ({{handle}})")
    (templates_dir / "SIBLINGS.md").write_text("Sibling: {{sibling_name}}")
    soul = tmp_path / "SOUL.md"
    soul.write_text("# Constitution")

    files = _build_template_files(
        templates_dir, soul, "lou", "lou.slopsalon.art", "other", "other.slopsalon.art"
    )

    assert files["SOUL.md"] == "# Constitution"
    assert files["CLAUDE.md"] == "Hi lou (lou.slopsalon.art)"
    assert files["SIBLINGS.md"] == "Sibling: other"


def test_provision_calls_steps_in_order(tmp_path, monkeypatch):
    """The provisioner orchestrates the workflow; verify the key external calls."""
    from slop_salon import provision

    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    (templates_dir / "CLAUDE.md").write_text("# {{name}} ({{handle}})")
    (templates_dir / "SIBLINGS.md").write_text("# Siblings of {{name}}")
    (templates_dir / "README.md").write_text("# {{name}}")
    (templates_dir / ".gitignore").write_text(".claude/\n")
    (templates_dir / ".pre-commit-config.yaml").write_text("repos: []\n")
    (templates_dir / "slop-tick").write_text("#!/bin/bash\n")
    (templates_dir / "slop-tick-loop").write_text("#!/bin/bash\n")

    soul = tmp_path / "SOUL.md"
    soul.write_text("# Soul")

    cfg = tmp_path / "slop_salon.toml"
    cfg.write_text(
        """
[agents.lou]
handle = "lou.slopsalon.art"
github_repo = "ANUcybernetics/slop-salon-lou"
sprite_id = ""
siblings = ["other"]
"""
    )

    monkeypatch.chdir(tmp_path)

    fake_secrets = {
        "BSKY_HANDLE": "lou.slopsalon.art",
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
        sprites.create_sprite.return_value = "lou"
        sprites.exec.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_sprites_class.return_value = sprites
        mock_sub.run.return_value = MagicMock(stdout="", returncode=0)

        provision.provision_agent("lou", skip_dns_confirm=True)

    gh_calls = [c for c in mock_sub.run.call_args_list if "gh" in c[0][0][0]]
    assert any("repo" in c[0][0] and "create" in c[0][0] for c in gh_calls)

    sprites.create_sprite.assert_called_once()

    # env-file write, apt, uv-install, clone+symlink, pre-commit, git-config,
    # tick-service = 7 execs
    assert sprites.exec.call_count >= 7

    # The tick service is created via sprite-env services, not crontab.
    exec_commands = [c[0][1][-1] for c in sprites.exec.call_args_list]
    assert any("sprite-env services create tick" in cmd for cmd in exec_commands)
    assert not any("crontab" in cmd for cmd in exec_commands)

    # claude is pre-installed in the sprite image, so provisioning must not reinstall it.
    assert not any("claude.ai/install.sh" in cmd for cmd in exec_commands)

    # The env file is written inside the sprite (the REST `env` field is ignored).
    assert any("~/.slop-env" in cmd for cmd in exec_commands)
    # create_sprite no longer takes env_vars (the API ignored them anyway).
    assert sprites.create_sprite.call_args.kwargs == {"name": "lou"} or (
        sprites.create_sprite.call_args.args == ("lou",)
    )

    from slop_salon.config import load_config

    reloaded = load_config(cfg)
    assert reloaded.agents["lou"].sprite_id == "lou"
