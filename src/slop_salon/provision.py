"""Provisioning: the agent repo is the source, the sprite is a cache built from it.

A sprite is create + clone + `setup.sh`, and nothing else; `recreate` runs the
same `bootstrap_sprite`. The bash that runs inside the sprite is built by pure
`_build_*` functions so each is testable on its own.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from pathlib import Path

import typer

from .config import Agent, Config, load_config, save_sprite_id
from .sprites import AGENT_LABEL, SpritesClient

# DNS egress allowlist applied to every agent sprite. `defaults` is the
# platform's development set (GitHub, npm, PyPI, the major AI APIs, ...); the
# rest is what the tools and the agents' own making reach for. The model is
# reached through api.sprites.dev, never OpenRouter directly.
EGRESS_RULES: list[dict[str, str]] = [
    {"include": "defaults"},
    *(
        {"domain": d, "action": "allow"}
        for d in (
            "api.sprites.dev",
            # Bluesky: auth entry point, the PDS shards, the AppView, blobs, video.
            "bsky.social",
            "*.bsky.network",
            "*.bsky.app",
            "bsky.app",
            "plc.directory",
            # Replicate and where its outputs are served from.
            "api.replicate.com",
            "*.replicate.delivery",
            "replicate.delivery",
            # Installers and system packages.
            "astral.sh",
            "*.astral.sh",
            "archive.ubuntu.com",
            "security.ubuntu.com",
            "ports.ubuntu.com",
            # Reading the world.
            "*.wikipedia.org",
            "*.wikimedia.org",
            "*.archive.org",
            "archive.org",
            "*.gutenberg.org",
            "slopsalon.art",
            "*.slopsalon.art",
        )
    ),
]


def _interpolate(text: str, agent: Agent, config: Config) -> str:
    siblings = [config.agents[s] for s in agent.siblings]
    prose = " and ".join(f"{s.name} (`{s.handle}`)" for s in siblings) or "nobody yet"
    listing = "\n".join(f"- {s.name}: `{s.handle}`" for s in siblings) or "Nobody yet."
    return (
        text.replace("{{name}}", agent.name)
        .replace("{{handle}}", agent.handle)
        .replace("{{siblings_prose}}", prose)
        .replace("{{siblings_list}}", listing)
    )


def build_template_files(
    config: Config,
    agent: Agent,
    templates_dir: str | Path = "templates",
    souls_dir: str | Path = "souls",
) -> dict[str, str]:
    """Every file in the agent's initial commit: the templates interpolated for
    this agent, plus its soul as `SOUL.md`. Paths are relative to the repo root."""
    if not agent.soul:
        raise ValueError(f"agent {agent.name!r} has no soul; set `soul` on its block")
    files = {"SOUL.md": (Path(souls_dir) / f"{agent.soul}.md").read_text()}
    root = Path(templates_dir)
    for tmpl in sorted(root.rglob("*")):
        if tmpl.is_file():
            files[str(tmpl.relative_to(root))] = _interpolate(tmpl.read_text(), agent, config)
    return files


def write_files(root: Path, files: dict[str, str]) -> None:
    """Materialise a path -> content map under `root`. Anything with a shebang
    is made executable so the mode lands in the commit."""
    for rel_path, content in files.items():
        target = root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        if content.startswith("#!"):
            target.chmod(0o755)


def push_initial_commit(repo: str, files: dict[str, str], token: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        clone = Path(tmp) / "repo"
        env = {**os.environ, "GH_TOKEN": token}
        subprocess.run(["gh", "repo", "clone", repo, str(clone)], check=True, env=env)
        write_files(clone, files)
        subprocess.run(["git", "add", "-A"], cwd=clone, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial provisioning commit"], cwd=clone, check=True
        )
        subprocess.run(["git", "push", "-u", "origin", "HEAD"], cwd=clone, check=True, env=env)


# --- In-sprite commands (pure builders) ---


def _build_clone_cmd(name: str, repo: str) -> str:
    """Clone the agent repo over plain HTTPS: it is public, and pushes get their
    token from the tick environment via the credential helper setup.sh sets."""
    return f"git clone --quiet https://github.com/{repo}.git ~/slop-salon-{shlex.quote(name)}"


def _build_setup_cmd(name: str) -> str:
    return f"cd ~/slop-salon-{shlex.quote(name)} && ./setup.sh"


def _build_claude_pin_cmd(version: str) -> str:
    """`claude install <version>` repoints the launcher at that native build;
    `--force` reinstalls over whatever the image shipped."""
    return f"claude install {shlex.quote(version)} --force"


def bootstrap_steps(name: str, repo: str, claude_version: str) -> list[tuple[str, str]]:
    """(label, bash) pairs that turn an empty sprite into a ticking one."""
    steps = [("clone repo", _build_clone_cmd(name, repo)), ("run setup.sh", _build_setup_cmd(name))]
    if claude_version:
        steps.append((f"pin claude {claude_version}", _build_claude_pin_cmd(claude_version)))
    return steps


def bootstrap_sprite(sprites: SpritesClient, config: Config, agent: Agent) -> None:
    """Label, fence and populate a freshly created sprite. Shared by `new` and
    `recreate`, so a rebuilt sprite is byte-for-byte a fresh one."""
    sprites.set_labels(agent.sprite_id, [AGENT_LABEL, f"salon={agent.salon}"])
    sprites.set_network_policy(agent.sprite_id, EGRESS_RULES)
    for label, command in bootstrap_steps(agent.name, agent.github_repo, config.claude_version):
        typer.echo(f"  -> {label}")
        result = sprites.exec(agent.sprite_id, ["bash", "-lc", command])
        if result.exit_code != 0:
            raise RuntimeError(
                f"{label} failed (exit={result.exit_code}): {result.stderr or result.stdout}"
            )


def provision_agent(
    name: str,
    config_path: str | Path = "slop_salon.toml",
    templates_dir: str | Path = "templates",
    souls_dir: str | Path = "souls",
    skip_dns_confirm: bool = False,
) -> None:
    """End-to-end provisioning for one agent already registered in the config."""
    config = load_config(config_path)
    if name not in config.agents:
        raise typer.BadParameter(f"agent {name!r} not in {config.path}")
    agent = config.agents[name]
    # Resolve everything that can fail on the admin box before anything is
    # created: a missing secret should cost nothing, not a half-built sprite.
    from .tick import tick_env

    tick_env(config, agent)
    gh_token = os.environ["SLOP_GH_TOKEN"]
    files = build_template_files(config, agent, templates_dir, souls_dir)

    # Repo creation runs as the admin box's own `gh` login: the slop token can
    # push to the agent repos but cannot create one in the org.
    gh_env = {k: v for k, v in os.environ.items() if k != "GH_TOKEN"}
    exists = (
        subprocess.run(
            ["gh", "repo", "view", agent.github_repo, "--json", "name"],
            capture_output=True,
            env=gh_env,
        ).returncode
        == 0
    )
    if exists:
        typer.echo(f"[1/5] GH repo {agent.github_repo} already exists, skipping create")
    else:
        typer.echo(f"[1/5] Creating GH repo {agent.github_repo}")
        subprocess.run(
            ["gh", "repo", "create", agent.github_repo, "--public"], check=True, env=gh_env
        )

    typer.echo("[2/5] Pushing templates as initial commit")
    push_initial_commit(agent.github_repo, files, gh_token)

    if skip_dns_confirm:
        typer.echo("[3/5] Skipping DNS confirm (--yes-dns)")
    else:
        typer.echo(f"[3/5] MANUAL: add the Bluesky DNS TXT record at _atproto.{agent.handle}")
        typer.confirm("Have you added the DNS record?", abort=True)

    typer.echo("[4/5] Creating sprite")
    sprites = SpritesClient()
    agent.sprite_id = sprites.create_sprite(name, labels=[AGENT_LABEL, f"salon={agent.salon}"])
    save_sprite_id(config, name, agent.sprite_id)
    bootstrap_sprite(sprites, config, agent)

    typer.echo(f"[5/5] Provisioned {name} -> sprite {agent.sprite_id}")
