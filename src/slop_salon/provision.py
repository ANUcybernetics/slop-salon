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
import tomllib
from pathlib import Path

import typer

from slop_salon.config import load_config, save_sprite_id
from slop_salon.sprites import SpritesClient

SPRITE_HOME = "/home/sprite"
# Default sprite image already ships git, curl, jq, node, python, go, ruby,
# rust, gh, plus claude/gemini/codex CLIs. Only media tooling is missing.
APT_PACKAGES = "imagemagick ffmpeg sox"
SLOP_SALON_REPO = "git+https://github.com/ANUcybernetics/slop-salon"


def resolve_secrets(
    name: str,
    all_agent_names: list[str],
    secrets_path: str | Path = "secrets.toml",
) -> dict[str, str]:
    """Resolve the env dict for a sprite-side install of `name`.

    Two sources, merged:
    - Shared admin tokens come from `SLOP_*` env vars (e.g. `SLOP_GH_TOKEN`
      → `GH_TOKEN`). Any `SLOP_<AGENT>_*` are skipped — per-agent secrets
      live in the file, not the env.
    - Per-agent secrets come from `[agents.<name>]` in `secrets_path`. TOML
      keys are uppercased into env names (bsky_password → BSKY_PASSWORD).
      File values win on key collision.

    Non-`SLOP_`-prefixed env vars (e.g. `SPRITES_API_TOKEN`) stay admin-side.
    """
    agent_prefixes = tuple(f"SLOP_{n.upper()}_" for n in all_agent_names)
    env: dict[str, str] = {}
    for k, v in os.environ.items():
        if k.startswith("SLOP_") and not k.startswith(agent_prefixes):
            env[k.removeprefix("SLOP_")] = v

    p = Path(secrets_path)
    if p.exists():
        with p.open("rb") as f:
            data = tomllib.load(f)
        agent_secrets = data.get("agents", {}).get(name, {})
        for k, v in agent_secrets.items():
            if v:  # skip empty placeholders
                env[k.upper()] = v
    return env


def _interpolate(
    text: str,
    name: str,
    handle: str,
    sibling: str = "",
    sibling_handle: str = "",
    namesake: str = "",
    namesake_url: str = "",
) -> str:
    return (
        text.replace("{{name}}", name)
        .replace("{{handle}}", handle)
        .replace("{{sibling_name}}", sibling)
        .replace("{{sibling_handle}}", sibling_handle)
        .replace("{{namesake}}", namesake)
        .replace("{{namesake_url}}", namesake_url)
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
        f"chmod +x {repo_dir}/slop-tick"
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
        # -u origin HEAD handles both empty repos (sets upstream + creates the
        # remote default branch) and pre-existing default branches uniformly.
        subprocess.run(
            ["git", "push", "-u", "origin", "HEAD"],
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
    namesake: str = "",
    namesake_url: str = "",
) -> dict[str, str]:
    """Read every template file, interpolate placeholders, return a name->content map."""
    files: dict[str, str] = {"SOUL.md": Path(soul_path).read_text()}
    for tmpl in templates_dir.iterdir():
        if tmpl.is_file():
            files[tmpl.name] = _interpolate(
                tmpl.read_text(),
                name,
                handle,
                sibling_name,
                sibling_handle,
                namesake,
                namesake_url,
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

    env = resolve_secrets(name, list(config.agents.keys()))
    gh_token = env.get("GH_TOKEN")
    if not gh_token:
        raise RuntimeError(
            f"GH_TOKEN missing from resolved env for {name!r}; "
            f"check ~/.config/mise/config.local.toml for SLOP_GH_TOKEN"
        )
    # BSKY_HANDLE is public config (lives in slop_salon.toml), not a secret;
    # inject it here so the sprite-side tools see it alongside the secrets.
    env["BSKY_HANDLE"] = agent.handle

    sibling_name = agent.siblings[0] if agent.siblings else ""
    sibling_handle = config.agents[sibling_name].handle if sibling_name in config.agents else ""
    templates_dir = Path(templates_dir)

    repo_exists = (
        subprocess.run(
            ["gh", "repo", "view", agent.github_repo, "--json", "name"],
            capture_output=True,
            env={**os.environ, "GH_TOKEN": gh_token},
        ).returncode
        == 0
    )
    if repo_exists:
        typer.echo(f"[1/11] GH repo {agent.github_repo} already exists, skipping create")
    else:
        typer.echo(f"[1/11] Creating GH repo {agent.github_repo}")
        subprocess.run(
            ["gh", "repo", "create", agent.github_repo, "--public"],
            check=True,
            env={**os.environ, "GH_TOKEN": gh_token},
        )

    typer.echo("[2/11] Pushing templates as initial commit")
    files = _build_template_files(
        templates_dir,
        Path(soul_path),
        agent.name,
        agent.handle,
        sibling_name,
        sibling_handle,
        agent.namesake,
        agent.namesake_url,
    )
    _push_initial_commit(agent.github_repo, files, gh_token)

    if not skip_dns_confirm:
        typer.echo(f"[3/11] MANUAL: add Bluesky DNS TXT record at _atproto.{agent.handle}")
        typer.confirm("Have you added the DNS record?", abort=True)
    else:
        typer.echo("[3/11] Skipping DNS confirm (--yes-dns set)")

    typer.echo("[4/11] Creating sprite")
    sprites = SpritesClient()
    sprite_id = sprites.create_sprite(name=name)

    def _exec(command: str) -> None:
        result = sprites.exec(sprite_id, ["bash", "-lc", command])
        if result.exit_code != 0:
            raise RuntimeError(
                f"sprite command failed (exit={result.exit_code}): {command}\n"
                f"stderr: {result.stderr}"
            )

    typer.echo("[5/11] Writing ~/.slop-env in sprite (secrets + AGENT_NAME)")
    _exec(_build_write_env_file_cmd({"AGENT_NAME": name, **env}))

    typer.echo("[6/11] Apt install (imagemagick, ffmpeg, sox)")
    _exec(_build_apt_install_cmd())

    typer.echo("[7/11] uv tool install slop-salon")
    _exec(_build_uv_and_slop_install_cmd())

    typer.echo("[8/11] Cloning agent repo + symlinking slop-tick into ~/.local/bin")
    repo_url = f"https://{gh_token}@github.com/{agent.github_repo}.git"
    _exec(_build_clone_and_symlink_cmd(name, repo_url))

    typer.echo("[9/11] pre-commit install")
    _exec(_build_pre_commit_install_cmd(name))

    typer.echo("[10/11] Configuring git in sprite")
    _exec(_build_git_config_cmd(name, gh_token))

    typer.echo(f"[11/11] Saving sprite_id to {config.path}")
    save_sprite_id(config, name, sprite_id)

    typer.echo(f"\nProvisioned {name} → sprite {sprite_id}")
