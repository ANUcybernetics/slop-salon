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


SIBLING_STUB = "(No observations yet. Update this file as you encounter their work.)"


def _render_sibling_block(name: str, handle: str) -> str:
    """One sibling entry as it appears in SIBLINGS.md."""
    return f"## {name}\n\nHandle: `{handle}`\n\n{SIBLING_STUB}"


def _build_siblings_section(siblings: list[tuple[str, str]]) -> str:
    """The body that replaces {{siblings_section}} in templates/SIBLINGS.md."""
    return "\n\n".join(_render_sibling_block(n, h) for n, h in siblings)


def _interpolate(
    text: str,
    name: str,
    handle: str,
    siblings_section: str = "",
) -> str:
    return (
        text.replace("{{name}}", name)
        .replace("{{handle}}", handle)
        .replace("{{siblings_section}}", siblings_section)
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


AMBIENT_HOOK_SCRIPT = """#!/bin/bash
# Ambient-memory recall hook (PostToolUse).
#
# Pipes the most recent tool's input through `slop-recall`, which scans the
# agent's notes/ for token-overlap matches and prints the top few as short
# snippets. Whatever it prints is wrapped as `hookSpecificOutput
# .additionalContext`, which Claude Code surfaces to the model alongside
# the next turn's tool result. Net effect: prior notebook lines surface
# without the agent having to grep.
#
# Fails open. Any error here (missing jq, missing slop-recall, malformed
# input) just means no injection --- the tick proceeds unchanged.
#
# Pattern: Tim Kellogg, "Ambient Associative Memory" (2026-05-17).
set -eu
input=$(cat)
query=$(printf '%s' "$input" | jq -r '.tool_input | tostring' 2>/dev/null || true)
[ -z "$query" ] && exit 0
snippets=$(printf '%s' "$query" | slop-recall 2>/dev/null || true)
[ -z "$snippets" ] && exit 0
jq -n --arg ctx "Past notes from your workshop:
$snippets" '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $ctx}}'
"""

# Python script that *merges* our PostToolUse hook into the sprite's
# existing ~/.claude/settings.json rather than overwriting it. The sprite
# image ships a settings.json with `defaultMode: bypassPermissions` plus
# `sprite-env-check.sh` hooks and an MCP-deny rule --- replacing that file
# (an earlier bug) broke bsky access for the agent. Merging preserves
# whatever else is there.
#
# Idempotent: any prior entry whose command ends in `ambient-recall.sh`
# is dropped before we re-append, regardless of how the path was written
# (~/, $HOME/, absolute).
SETTINGS_MERGE_SCRIPT = """
import json
from pathlib import Path

OUR_ENTRY = {
    "matcher": "Read|Grep|Glob|Bash",
    "hooks": [{"type": "command", "command": "$HOME/.claude/hooks/ambient-recall.sh"}],
}

p = Path.home() / ".claude" / "settings.json"
existing = json.loads(p.read_text()) if p.exists() else {}

hooks = existing.setdefault("hooks", {})
post = hooks.setdefault("PostToolUse", [])
post = [
    e for e in post
    if not any("ambient-recall.sh" in h.get("command", "") for h in e.get("hooks", []))
]
post.append(OUR_ENTRY)
hooks["PostToolUse"] = post

p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(existing, indent=2))
"""


def _build_install_ambient_hook_cmd() -> str:
    """Install the ambient-recall hook and merge its settings entry on the sprite.

    Idempotent: re-running reinstalls the hook script and re-merges its
    settings entry (without duplicating it) into whatever else is already
    in ~/.claude/settings.json.
    """
    script_b64 = base64.b64encode(AMBIENT_HOOK_SCRIPT.encode()).decode()
    merge_b64 = base64.b64encode(SETTINGS_MERGE_SCRIPT.encode()).decode()
    return (
        "mkdir -p ~/.claude/hooks && "
        f"echo {script_b64} | base64 -d > ~/.claude/hooks/ambient-recall.sh && "
        "chmod +x ~/.claude/hooks/ambient-recall.sh && "
        f"echo {merge_b64} | base64 -d | python3"
    )


def _build_tailscale_join_cmd(name: str) -> str:
    """Install Tailscale and join the tailnet.

    The sprite reaches vLLM over the tailnet. Sprites have no systemd, so
    tailscaled runs as a plain detached daemon; `slop-tick` re-ensures it
    each tick. Reads TAILSCALE_AUTHKEY from ~/.slop-env --- so this must run
    after the env-file write step.
    """
    return (
        'V=$(curl -s "https://pkgs.tailscale.com/stable/?mode=json" '
        "| jq -r .Tarballs.amd64) && "
        'curl -fsSL "https://pkgs.tailscale.com/stable/$V" -o /tmp/ts.tgz && '
        "tar xzf /tmp/ts.tgz -C /tmp && "
        'D=$(find /tmp -maxdepth 1 -type d -name "tailscale_*_amd64") && '
        'sudo cp "$D/tailscale" "$D/tailscaled" /usr/local/bin/ && '
        "sudo install -d -m 755 /var/run/tailscale /var/lib/tailscale && "
        'sudo bash -c "setsid /usr/local/bin/tailscaled '
        "--state=/var/lib/tailscale/tailscaled.state "
        "--socket=/var/run/tailscale/tailscaled.sock "
        '>/var/log/tailscaled.log 2>&1 </dev/null &" && '
        "sleep 5 && "
        "source ~/.slop-env && "
        'sudo /usr/local/bin/tailscale up --authkey="$TAILSCALE_AUTHKEY" '
        f"--hostname=slop-{shlex.quote(name)} --accept-dns=false"
    )


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
    siblings: list[tuple[str, str]],
) -> dict[str, str]:
    """Read every template file, interpolate placeholders, return a name->content map."""
    siblings_section = _build_siblings_section(siblings)
    files: dict[str, str] = {"SOUL.md": Path(soul_path).read_text()}
    for tmpl in templates_dir.iterdir():
        if tmpl.is_file():
            files[tmpl.name] = _interpolate(
                tmpl.read_text(),
                name,
                handle,
                siblings_section,
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

    siblings = [(s, config.agents[s].handle) for s in agent.siblings if s in config.agents]
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
        typer.echo(f"[1/12] GH repo {agent.github_repo} already exists, skipping create")
    else:
        typer.echo(f"[1/12] Creating GH repo {agent.github_repo}")
        subprocess.run(
            ["gh", "repo", "create", agent.github_repo, "--public"],
            check=True,
            env={**os.environ, "GH_TOKEN": gh_token},
        )

    typer.echo("[2/12] Pushing templates as initial commit")
    files = _build_template_files(
        templates_dir,
        Path(soul_path),
        agent.name,
        agent.handle,
        siblings,
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

    typer.echo("[6/12] Installing Tailscale and joining the tailnet")
    _exec(_build_tailscale_join_cmd(name))

    typer.echo("[7/12] Apt install (imagemagick, ffmpeg, sox)")
    _exec(_build_apt_install_cmd())

    typer.echo("[8/13] uv tool install slop-salon")
    _exec(_build_uv_and_slop_install_cmd())

    typer.echo("[9/13] Installing ambient-recall hook + Claude Code settings")
    _exec(_build_install_ambient_hook_cmd())

    typer.echo("[10/13] Cloning agent repo + symlinking slop-tick into ~/.local/bin")
    repo_url = f"https://{gh_token}@github.com/{agent.github_repo}.git"
    _exec(_build_clone_and_symlink_cmd(name, repo_url))

    typer.echo("[11/13] pre-commit install")
    _exec(_build_pre_commit_install_cmd(name))

    typer.echo("[12/13] Configuring git in sprite")
    _exec(_build_git_config_cmd(name, gh_token))

    typer.echo(f"[13/13] Saving sprite_id to {config.path}")
    save_sprite_id(config, name, sprite_id)

    typer.echo(f"\nProvisioned {name} → sprite {sprite_id}")
