"""Tests for slop_salon.provision."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch


def test_resolve_secrets_merges_shared_env_and_per_agent_file(monkeypatch, tmp_path):
    from slop_salon.provision import resolve_secrets

    for k in list(os.environ):
        if k.startswith("SLOP_"):
            monkeypatch.delenv(k, raising=False)

    monkeypatch.setenv("SLOP_GH_TOKEN", "ghp_shared")
    monkeypatch.setenv("SLOP_ANTHROPIC_BASE_URL", "https://proxy")
    # Non-SLOP_ env vars are not propagated — SPRITES_API_TOKEN stays admin-side.
    monkeypatch.setenv("SPRITES_API_TOKEN", "not-leaked-to-sprite")

    secrets = tmp_path / "secrets.toml"
    secrets.write_text(
        """
[agents.lou]
bsky_password = "lou-pw"
replicate_api_token = "lou-replicate"
"""
    )

    env = resolve_secrets("lou", ["lou", "mina"], secrets_path=secrets)

    assert env["BSKY_PASSWORD"] == "lou-pw"
    assert env["REPLICATE_API_TOKEN"] == "lou-replicate"
    assert env["GH_TOKEN"] == "ghp_shared"
    assert env["ANTHROPIC_BASE_URL"] == "https://proxy"
    assert "SPRITES_API_TOKEN" not in env


def test_resolve_secrets_excludes_other_agents_from_file(monkeypatch, tmp_path):
    from slop_salon.provision import resolve_secrets

    for k in list(os.environ):
        if k.startswith("SLOP_"):
            monkeypatch.delenv(k, raising=False)

    secrets = tmp_path / "secrets.toml"
    secrets.write_text(
        """
[agents.lou]
bsky_password = "lou-pw"

[agents.mina]
bsky_password = "mina-pw"
"""
    )

    env = resolve_secrets("lou", ["lou", "mina"], secrets_path=secrets)

    assert env["BSKY_PASSWORD"] == "lou-pw"
    # Mina's secrets must not land in lou's sprite.
    assert all(not k.startswith("MINA_") for k in env)


def test_resolve_secrets_ignores_stray_per_agent_env_vars(monkeypatch, tmp_path):
    """If someone leaves a SLOP_<AGENT>_* env var around, it must not leak in."""
    from slop_salon.provision import resolve_secrets

    for k in list(os.environ):
        if k.startswith("SLOP_"):
            monkeypatch.delenv(k, raising=False)

    # Stray env vars from the old convention — should be ignored entirely.
    monkeypatch.setenv("SLOP_LOU_BSKY_PASSWORD", "from-env-should-not-win")
    monkeypatch.setenv("SLOP_MINA_BSKY_PASSWORD", "from-env-should-not-win")

    env = resolve_secrets("lou", ["lou", "mina"], secrets_path=tmp_path / "missing.toml")

    assert "BSKY_PASSWORD" not in env


def test_resolve_secrets_skips_empty_placeholders(monkeypatch, tmp_path):
    from slop_salon.provision import resolve_secrets

    for k in list(os.environ):
        if k.startswith("SLOP_"):
            monkeypatch.delenv(k, raising=False)

    secrets = tmp_path / "secrets.toml"
    secrets.write_text(
        """
[agents.gert]
bsky_password = ""
anthropic_api_key = "real-value"
"""
    )

    env = resolve_secrets("gert", ["gert"], secrets_path=secrets)

    assert env["ANTHROPIC_API_KEY"] == "real-value"
    assert "BSKY_PASSWORD" not in env


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


def test_claude_pin_cmd_installs_explicit_known_good_version():
    from slop_salon.provision import CLAUDE_VERSION, _build_claude_pin_cmd

    cmd = _build_claude_pin_cmd()
    assert cmd == f"claude install {CLAUDE_VERSION} --force"
    # Must be an explicit version, never a moving channel: a recreate off a newer
    # base image must not drift onto a build whose Skills injection vLLM rejects.
    assert CLAUDE_VERSION not in ("latest", "stable")
    assert CLAUDE_VERSION[0].isdigit()


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
    # Ticks come from the external wake driver; no in-sprite loop.
    assert "slop-tick-loop" not in cmd


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


def test_tailscale_join_cmd_installs_and_joins():
    from slop_salon.provision import _build_tailscale_join_cmd

    cmd = _build_tailscale_join_cmd("lou")
    assert "pkgs.tailscale.com" in cmd
    assert "tailscaled" in cmd
    assert 'tailscale up --authkey="$TAILSCALE_AUTHKEY"' in cmd
    assert "--hostname=slop-lou" in cmd
    # The auth key is read from ~/.slop-env, not embedded in the command.
    assert "source ~/.slop-env" in cmd


def test_build_template_files_interpolates_placeholders(tmp_path):
    from slop_salon.provision import _build_template_files

    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    (templates_dir / "CLAUDE.md").write_text("Hi {{name}} ({{handle}})")
    (templates_dir / "SIBLINGS.md").write_text("Siblings:\n\n{{siblings_section}}")
    soul = tmp_path / "SOUL.md"
    soul.write_text("# Constitution")

    files = _build_template_files(
        templates_dir,
        soul,
        "lou",
        "lou.slopsalon.art",
        [("mina", "mina.slopsalon.art"), ("gert", "gert.slopsalon.art")],
    )

    assert files["SOUL.md"] == "# Constitution"
    assert files["CLAUDE.md"] == "Hi lou (lou.slopsalon.art)"
    assert "## mina" in files["SIBLINGS.md"]
    assert "Handle: `mina.slopsalon.art`" in files["SIBLINGS.md"]
    assert "## gert" in files["SIBLINGS.md"]
    assert "Handle: `gert.slopsalon.art`" in files["SIBLINGS.md"]


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
        "BSKY_PASSWORD": "x",
        "REPLICATE_API_TOKEN": "y",
        "ANTHROPIC_API_KEY": "z",
        "GH_TOKEN": "ghp_xxx",
    }

    def _fake_subprocess_run(args, **kwargs):
        # `gh repo view` is the idempotency probe; returncode=1 means
        # "repo does not exist" so the create branch runs.
        if isinstance(args, list) and len(args) >= 3 and args[:3] == ["gh", "repo", "view"]:
            return MagicMock(stdout="", returncode=1)
        return MagicMock(stdout="", returncode=0)

    with (
        patch.object(provision, "resolve_secrets", return_value=fake_secrets),
        patch.object(provision, "SpritesClient") as mock_sprites_class,
        patch.object(provision, "subprocess") as mock_sub,
    ):
        sprites = MagicMock()
        sprites.create_sprite.return_value = "lou"
        sprites.exec.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_sprites_class.return_value = sprites
        mock_sub.run.side_effect = _fake_subprocess_run

        provision.provision_agent("lou", skip_dns_confirm=True)

    gh_calls = [c for c in mock_sub.run.call_args_list if "gh" in c[0][0][0]]
    assert any("repo" in c[0][0] and "create" in c[0][0] for c in gh_calls)

    sprites.create_sprite.assert_called_once()

    # env-file write, tailscale, apt, claude-pin, uv-install, ambient-hook,
    # clone+symlink, pre-commit, git-config = 9 execs
    assert sprites.exec.call_count >= 9

    # Ticks are driven by the external wake driver (slop-wake.timer), not an
    # in-sprite service or cron. Provisioning must not create one.
    exec_commands = [c[0][1][-1] for c in sprites.exec.call_args_list]
    assert not any("sprite-env services create tick" in cmd for cmd in exec_commands)
    assert not any("crontab" in cmd for cmd in exec_commands)

    # claude ships in the base image but its version drifts with the image, so
    # provisioning pins it to a known-good build via the native `claude install`
    # subcommand (never the curl installer).
    from slop_salon.provision import CLAUDE_VERSION

    assert any(f"claude install {CLAUDE_VERSION}" in cmd for cmd in exec_commands)
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


def _run_merge_script(home_dir):
    """Exec SETTINGS_MERGE_SCRIPT against a Path.home() set to home_dir."""
    import os

    from slop_salon.provision import SETTINGS_MERGE_SCRIPT

    old_home = os.environ.get("HOME")
    os.environ["HOME"] = str(home_dir)
    try:
        exec(SETTINGS_MERGE_SCRIPT, {"__name__": "__main__"})
    finally:
        if old_home is None:
            del os.environ["HOME"]
        else:
            os.environ["HOME"] = old_home


def test_settings_merge_preserves_existing_permissions_and_hooks(tmp_path):
    import json

    (tmp_path / ".claude").mkdir()
    initial = {
        "permissions": {"defaultMode": "bypassPermissions"},
        "hooks": {
            "PreToolUse": [
                {"matcher": "^mcp__", "hooks": [{"type": "command", "command": "deny"}]}
            ],
            "PostToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "sprite-env-check"}]}
            ],
            "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "sprite-env-check"}]}],
        },
    }
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps(initial))

    _run_merge_script(tmp_path)

    result = json.loads((tmp_path / ".claude" / "settings.json").read_text())

    assert result["permissions"] == {"defaultMode": "bypassPermissions"}
    assert result["hooks"]["PreToolUse"] == initial["hooks"]["PreToolUse"]
    assert result["hooks"]["UserPromptSubmit"] == initial["hooks"]["UserPromptSubmit"]
    post = result["hooks"]["PostToolUse"]
    assert any(e["matcher"] == "Bash" for e in post), "sprite-env-check entry must survive"
    assert any(
        any("ambient-recall.sh" in h.get("command", "") for h in e.get("hooks", [])) for e in post
    ), "ambient-recall entry must be present"


def test_settings_merge_is_idempotent(tmp_path):
    import json

    (tmp_path / ".claude").mkdir()
    initial = {"hooks": {"PostToolUse": []}}
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps(initial))

    _run_merge_script(tmp_path)
    after_first = json.loads((tmp_path / ".claude" / "settings.json").read_text())

    _run_merge_script(tmp_path)
    after_second = json.loads((tmp_path / ".claude" / "settings.json").read_text())

    assert after_first == after_second
    ambient_count = sum(
        1
        for e in after_second["hooks"]["PostToolUse"]
        if any("ambient-recall.sh" in h.get("command", "") for h in e.get("hooks", []))
    )
    assert ambient_count == 1, "should not duplicate on reinstall"


def test_settings_merge_replaces_stale_path_variant(tmp_path):
    """A pre-existing entry that uses ~/ instead of $HOME/ should be replaced."""
    import json

    (tmp_path / ".claude").mkdir()
    initial = {
        "hooks": {
            "PostToolUse": [
                {
                    "matcher": "Read|Bash",
                    "hooks": [{"type": "command", "command": "~/.claude/hooks/ambient-recall.sh"}],
                }
            ]
        }
    }
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps(initial))

    _run_merge_script(tmp_path)

    post = json.loads((tmp_path / ".claude" / "settings.json").read_text())["hooks"]["PostToolUse"]
    assert len(post) == 1
    assert post[0]["hooks"][0]["command"] == "$HOME/.claude/hooks/ambient-recall.sh"


def test_settings_merge_handles_missing_file(tmp_path):
    import json

    _run_merge_script(tmp_path)

    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert "PostToolUse" in settings["hooks"]
    assert any(
        any("ambient-recall.sh" in h.get("command", "") for h in e.get("hooks", []))
        for e in settings["hooks"]["PostToolUse"]
    )
