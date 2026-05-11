"""Per-agent provisioning workflow.

Idempotent where possible (GitHub repo creation will fail loudly if the repo
already exists; the cleanest re-provision flow is to delete and recreate).

The bash commands run inside the sprite are built by pure `_build_*_cmd`
functions so each is unit-testable in isolation. `provision_agent` is a thin
orchestrator that composes them.
"""

from __future__ import annotations

import base64
import os
import shlex
import subprocess
from pathlib import Path

import typer

from slop_salon.config import load_config, save_sprite_id
from slop_salon.sprites import SpritesClient

SPRITE_HOME = "/home/sprite"
# Default sprite image already ships git, curl, jq, node, python, go, ruby,
# rust, gh, plus claude/gemini/codex CLIs. Only media tooling is missing.
APT_PACKAGES = "imagemagick ffmpeg sox"
SLOP_SALON_REPO = "git+https://github.com/ANUcybernetics/slop-salon"


def resolve_secrets_via_fnox(profile: str) -> dict[str, str]:
    """Run `fnox exec --profile <profile> -- env` and parse resolved env vars."""
    result = subprocess.run(
        ["fnox", "exec", "--profile", profile, "--", "env"],
        capture_output=True,
        text=True,
        check=True,
    )
    env: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key] = value
    return env


def _interpolate(
    text: str, name: str, handle: str, sibling: str = "", sibling_handle: str = ""
) -> str:
    return (
        text.replace("{{name}}", name)
        .replace("{{handle}}", handle)
        .replace("{{sibling_name}}", sibling)
        .replace("{{sibling_handle}}", sibling_handle)
    )


# --- Pure command builders (testable in isolation) ---


def _build_apt_install_cmd() -> str:
    return f"sudo apt-get update && sudo apt-get install -y {APT_PACKAGES}"


def _build_uv_and_slop_install_cmd() -> str:
    return (
        "curl -LsSf https://astral.sh/uv/install.sh | sh && "
        f"~/.local/bin/uv tool install {SLOP_SALON_REPO}"
    )


def _build_clone_and_symlink_cmd(name: str, repo_url: str) -> str:
    repo_dir = f"~/slop-salon-{name}"
    return (
        f"git clone {shlex.quote(repo_url)} {repo_dir} && "
        "mkdir -p ~/.local/bin && "
        f"ln -sf {repo_dir}/slop-tick ~/.local/bin/slop-tick && "
        f"ln -sf {repo_dir}/slop-tick-loop ~/.local/bin/slop-tick-loop && "
        f"chmod +x {repo_dir}/slop-tick {repo_dir}/slop-tick-loop"
    )


def _build_pre_commit_install_cmd(name: str) -> str:
    return (
        f"~/.local/bin/uv tool install pre-commit && cd ~/slop-salon-{name} && pre-commit install"
    )


def _build_git_config_cmd(name: str, gh_token: str) -> str:
    """Configure git in the sprite. Token stored plain-text; chmod 600 limits exposure."""
    return (
        f"cd ~/slop-salon-{name} && "
        f"git config user.name {shlex.quote(name)} && "
        f"git config user.email {shlex.quote(f'{name}@slopsalon.art')} && "
        "git config credential.helper store && "
        f"echo 'https://{gh_token}@github.com' > ~/.git-credentials && "
        "chmod 600 ~/.git-credentials"
    )


def _build_write_env_file_cmd(env: dict[str, str]) -> str:
    """Write resolved secrets to `~/.slop-env` (mode 600) inside the sprite.

    sprites.dev has no API for setting env vars from outside, so secrets
    have to live as a file inside the sprite. `slop-tick` sources this file
    at the top of every invocation so `claude` and the tools see the right
    env. The body is base64-encoded to avoid shell-quoting hazards.
    """
    body = "\n".join(f"export {k}={shlex.quote(v)}" for k, v in sorted(env.items()))
    encoded = base64.b64encode(body.encode()).decode()
    return f"umask 077 && echo {encoded} | base64 -d > ~/.slop-env && chmod 600 ~/.slop-env"


def _build_create_tick_service_cmd() -> str:
    """Register the tick loop as a sprite-env service so it survives reboots.

    The sprite image has no cron/systemd; long-running work must be a sprite
    service. The loop script is `slop-tick-loop` (symlinked into ~/.local/bin
    in the clone step).
    """
    return "sprite-env services create tick --cmd /home/sprite/.local/bin/slop-tick-loop"


# --- Step helpers (each does one logical step from the spec) ---


def _push_initial_commit(repo: str, files: dict[str, str], token: str) -> None:
    """Create an initial commit on the GH repo via a temp clone + push.

    `files` is a path-relative-to-repo-root → content map.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / "repo"
        subprocess.run(
            ["gh", "repo", "clone", repo, str(tmp_path)],
            check=True,
            env={**os.environ, "GH_TOKEN": token},
        )
        for rel_path, content in files.items():
            target = tmp_path / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial provisioning commit"],
            cwd=tmp_path,
            check=True,
        )
        subprocess.run(
            ["git", "push"],
            cwd=tmp_path,
            check=True,
            env={**os.environ, "GH_TOKEN": token},
        )


def _build_template_files(
    templates_dir: Path,
    soul_path: Path,
    name: str,
    handle: str,
    sibling_name: str,
    sibling_handle: str,
) -> dict[str, str]:
    """Read every template file, interpolate placeholders, return a name->content map."""
    files: dict[str, str] = {"SOUL.md": Path(soul_path).read_text()}
    for tmpl in templates_dir.iterdir():
        if tmpl.is_file():
            files[tmpl.name] = _interpolate(
                tmpl.read_text(), name, handle, sibling_name, sibling_handle
            )
    return files


# --- Orchestrator ---


def provision_agent(
    name: str,
    config_path: str | Path = "slop_salon.toml",
    templates_dir: str | Path = "templates",
    soul_path: str | Path = "SOUL.md",
    skip_dns_confirm: bool = False,
) -> None:
    """End-to-end provisioning for one agent."""
    config = load_config(config_path)
    if name not in config.agents:
        raise typer.BadParameter(f"agent {name!r} not in {config.path}")
    agent = config.agents[name]

    env = resolve_secrets_via_fnox(name)
    gh_token = env.get("GH_TOKEN")
    if not gh_token:
        raise RuntimeError(f"GH_TOKEN missing from fnox profile {name!r}; check fnox.toml")

    sibling_name = agent.siblings[0] if agent.siblings else ""
    sibling_handle = config.agents[sibling_name].handle if sibling_name in config.agents else ""
    templates_dir = Path(templates_dir)

    typer.echo(f"[1/12] Creating GH repo {agent.github_repo}")
    # --add-readme creates an initial commit so the repo has a default branch;
    # without it, the subsequent clone-and-push fails on an empty repo.
    subprocess.run(
        ["gh", "repo", "create", agent.github_repo, "--public", "--add-readme"],
        check=True,
        env={**os.environ, "GH_TOKEN": gh_token},
    )

    typer.echo("[2/12] Pushing templates as initial commit")
    files = _build_template_files(
        templates_dir, Path(soul_path), agent.name, agent.handle, sibling_name, sibling_handle
    )
    _push_initial_commit(agent.github_repo, files, gh_token)

    if not skip_dns_confirm:
        typer.echo(f"[3/12] MANUAL: add Bluesky DNS TXT record at _atproto.{agent.handle}")
        typer.confirm("Have you added the DNS record?", abort=True)
    else:
        typer.echo("[3/12] Skipping DNS confirm (--yes-dns set)")

    typer.echo("[4/12] Creating sprite")
    sprites = SpritesClient()
    sprite_id = sprites.create_sprite(name=name)

    def _exec(command: str) -> None:
        result = sprites.exec(sprite_id, ["bash", "-lc", command])
        if result.exit_code != 0:
            raise RuntimeError(
                f"sprite command failed (exit={result.exit_code}): {command}\n"
                f"stderr: {result.stderr}"
            )

    typer.echo("[5/12] Writing ~/.slop-env in sprite (secrets + AGENT_NAME)")
    _exec(_build_write_env_file_cmd({"AGENT_NAME": name, **env}))

    typer.echo("[6/12] Apt install (imagemagick, ffmpeg, sox)")
    _exec(_build_apt_install_cmd())

    typer.echo("[7/12] uv tool install slop-salon")
    _exec(_build_uv_and_slop_install_cmd())

    typer.echo("[8/12] Cloning agent repo + symlinking slop-tick(-loop) into ~/.local/bin")
    repo_url = f"https://{gh_token}@github.com/{agent.github_repo}.git"
    _exec(_build_clone_and_symlink_cmd(name, repo_url))

    typer.echo("[9/12] pre-commit install")
    _exec(_build_pre_commit_install_cmd(name))

    typer.echo("[10/12] Configuring git in sprite")
    _exec(_build_git_config_cmd(name, gh_token))

    typer.echo("[11/12] Creating sprite-env tick service")
    _exec(_build_create_tick_service_cmd())

    typer.echo(f"[12/12] Saving sprite_id to {config.path}")
    save_sprite_id(config, name, sprite_id)

    typer.echo(f"\nProvisioned {name} → sprite {sprite_id}")
