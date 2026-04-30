"""Per-agent provisioning workflow.

Implements the 13-step checklist from the spec. Idempotent where possible
(GitHub repo creation will fail loudly if it already exists; the cleanest
re-provision flow is to delete and recreate).
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import typer

from slop_studio.config import load_config, save_sprite_id
from slop_studio.sprites import SpritesClient

# Where the agent's repo gets cloned inside the sprite.
SPRITE_HOME = "/home/agent"
APT_PACKAGES = "git imagemagick ffmpeg sox jq curl python3.14 nodejs"


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


def _push_initial_commit(repo: str, files: dict[str, str], token: str) -> None:
    """Create an initial commit on the GH repo via a temp clone + push.

    `files` is a path-relative-to-repo-root → content map.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / "repo"
        # gh repo clone uses the configured GH_TOKEN
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


def provision_agent(
    name: str,
    config_path: str | Path = "slop_studio.toml",
    templates_dir: str | Path = "templates",
    soul_path: str | Path = "SOUL.md",
    skip_dns_confirm: bool = False,
) -> None:
    """End-to-end provisioning for one agent. Implements steps 1-13 from spec."""
    config = load_config(config_path)
    if name not in config.agents:
        raise typer.BadParameter(f"agent {name!r} not in {config.path}")
    agent = config.agents[name]

    # Resolve secrets early so we have GH_TOKEN before the gh calls.
    env = resolve_secrets_via_fnox(name)
    gh_token = env.get("GH_TOKEN")
    if not gh_token:
        raise RuntimeError(f"GH_TOKEN missing from fnox profile {name!r}; check fnox.toml")

    typer.echo(f"[1/13] Creating GH repo {agent.github_repo}")
    subprocess.run(
        ["gh", "repo", "create", agent.github_repo, "--public"],
        check=True,
        env={**os.environ, "GH_TOKEN": gh_token},
    )

    typer.echo("[2/13] Pushing templates as initial commit")
    sibling_name = agent.siblings[0] if agent.siblings else ""
    sibling_handle = ""
    if sibling_name in config.agents:
        sibling_handle = config.agents[sibling_name].handle

    templates_dir = Path(templates_dir)
    soul_text = Path(soul_path).read_text()
    files: dict[str, str] = {"SOUL.md": soul_text}
    for tmpl in templates_dir.iterdir():
        if tmpl.is_file():
            interpolated = _interpolate(
                tmpl.read_text(), agent.name, agent.handle, sibling_name, sibling_handle
            )
            files[tmpl.name] = interpolated
    _push_initial_commit(agent.github_repo, files, gh_token)

    if not skip_dns_confirm:
        typer.echo(f"[3/13] MANUAL: add Bluesky DNS TXT record at _atproto.{agent.handle}")
        typer.confirm("Have you added the DNS record?", abort=True)
    else:
        typer.echo("[3/13] Skipping DNS confirm (--yes-dns set)")

    typer.echo("[4/13] Creating sprite")
    sprites = SpritesClient()
    sprite_id = sprites.create_sprite(name=name, env_vars={"AGENT_NAME": name, **env})

    def _exec(command: str) -> None:
        result = sprites.exec(sprite_id, ["bash", "-lc", command])
        if result.exit_code != 0:
            raise RuntimeError(
                f"sprite command failed (exit={result.exit_code}): {command}\n"
                f"stderr: {result.stderr}"
            )

    typer.echo("[5/13] Apt install")
    _exec(f"sudo apt-get update && sudo apt-get install -y {APT_PACKAGES}")

    typer.echo("[6/13] Installing claude CLI")
    _exec("curl -fsSL https://claude.ai/install.sh | bash")

    typer.echo("[7/13] uv tool install slop-studio")
    _exec(
        "curl -LsSf https://astral.sh/uv/install.sh | sh && "
        "~/.local/bin/uv tool install git+https://github.com/ANUcybernetics/slop-studio"
    )

    typer.echo("[8/13] Cloning agent repo")
    repo_url = f"https://{gh_token}@github.com/{agent.github_repo}.git"
    _exec(f"git clone {shlex.quote(repo_url)} ~/slop-studio-{name}")

    typer.echo("[9/13] pre-commit install")
    _exec(f"cd ~/slop-studio-{name} && pip install pre-commit && pre-commit install")

    typer.echo("[10/13] Env vars already pushed via create_sprite")

    typer.echo("[11/13] Configuring git in sprite")
    _exec(
        f"cd ~/slop-studio-{name} && "
        f"git config user.name {shlex.quote(name)} && "
        f"git config user.email {shlex.quote(f'{name}@slopsalon.art')} && "
        "git config credential.helper store && "
        f"echo 'https://{gh_token}@github.com' > ~/.git-credentials"
    )

    typer.echo("[12/13] Installing crontab")
    crontab_text = (templates_dir / "crontab").read_text()
    _exec(f"echo {shlex.quote(crontab_text)} | crontab -")

    typer.echo(f"[13/13] Saving sprite_id to {config.path}")
    save_sprite_id(config, name, sprite_id)

    typer.echo(f"\nProvisioned {name} → sprite {sprite_id}")
