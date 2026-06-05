"""Recreate a wedged agent sprite while preserving its GitHub repo state.

Shared by `ops/recreate-sprite.py` (the CLI entry point) and the wake driver's
self-heal (`slop_salon.healing`). Unlike `slop new`, this does NOT re-push
templates --- the GH repo's drifted `CLAUDE.md` / `SIBLINGS.md` / `notes` are
preserved, and any admin bugfix commits already pushed flow into the fresh
sprite via `git clone`.
"""

from __future__ import annotations

import subprocess
import time

from .config import load_config
from .provision import (
    _build_apt_install_cmd,
    _build_clone_and_symlink_cmd,
    _build_git_config_cmd,
    _build_pre_commit_install_cmd,
    _build_tailscale_join_cmd,
    _build_uv_and_slop_install_cmd,
    _build_write_env_file_cmd,
    resolve_secrets,
)
from .sprites import SpritesClient


def recreate(
    name: str,
    config_path: str = "slop_salon.toml",
    sprites: SpritesClient | None = None,
) -> None:
    """Destroy and rebuild agent `name`'s sprite, cloning its repo from GitHub.

    `sprites` may be passed in to reuse an existing client (the wake driver
    does this); otherwise a fresh one is created.
    """
    config = load_config(config_path)
    if name not in config.agents:
        raise SystemExit(f"agent {name!r} missing from {config_path}")
    agent = config.agents[name]

    env = resolve_secrets(name, list(config.agents.keys()))
    missing = [
        k for k in ("GH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN") if not env.get(k)
    ]
    if missing:
        raise SystemExit(
            f"missing {missing} in resolved env; check "
            f"~/.config/mise/config.local.toml for the SLOP_* equivalents"
        )
    env["BSKY_HANDLE"] = agent.handle
    gh_token = env["GH_TOKEN"]

    sprites = sprites or SpritesClient()

    print(f"[1/9] Destroying old sprite {name!r}")
    subprocess.run(["sprite", "destroy", "-s", name, "--force"], check=True)

    print(f"[2/9] Creating fresh sprite {name!r}")
    sprites.create_sprite(name=name)
    # sprites.dev sometimes 404s the first exec immediately after create.
    time.sleep(3)

    def _exec(label: str, cmd: str) -> None:
        print(f"  -> {label}")
        result = sprites.exec(name, ["bash", "-lc", cmd])
        if result.exit_code != 0:
            raise RuntimeError(
                f"step {label!r} failed (exit={result.exit_code}):\n"
                f"STDOUT: {result.stdout[-2000:]}\n"
                f"STDERR: {result.stderr[-2000:]}"
            )

    print("[3/9] Writing ~/.slop-env (secrets + AGENT_NAME)")
    _exec("write env", _build_write_env_file_cmd({"AGENT_NAME": name, **env}))

    print("[4/9] Installing Tailscale and joining the tailnet")
    _exec("tailscale", _build_tailscale_join_cmd(name))

    print("[5/9] Apt install (imagemagick, ffmpeg, sox)")
    _exec("apt", _build_apt_install_cmd())

    print("[6/9] uv tool install slop-salon")
    _exec("uv install", _build_uv_and_slop_install_cmd())

    print("[7/9] Cloning agent repo from GH (preserves drift)")
    repo_url = f"https://{gh_token}@github.com/{agent.github_repo}.git"
    _exec("clone", _build_clone_and_symlink_cmd(name, repo_url))

    print("[8/9] pre-commit install")
    _exec("pre-commit", _build_pre_commit_install_cmd(name))

    print("[9/9] git config")
    _exec("git config", _build_git_config_cmd(name, gh_token))

    print(f"Done --- {name} ready.")
