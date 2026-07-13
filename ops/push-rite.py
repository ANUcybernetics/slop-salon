"""Push a one-shot rite into one live agent's GH repo as `RITE.md`.

A rite is a single instruction the agent performs on its next tick and then
deletes (tick-routine step 2). Rites live in `ops/rites/`; this script copies
one into an agent's repo root as `RITE.md`, commits, and pushes. The next
tick's `git pull --rebase` inside the sprite picks it up.

Unlike `push-template.py`, the rite body is copied verbatim --- rites carry no
`{{name}}`-style placeholders. If the agent already has a `RITE.md` (a rite it
has not yet performed), this refuses rather than clobber it.

Run from the project root:

    mise exec -- uv run python ops/push-rite.py <agent-name> ops/rites/<rite>.md

Example:

    mise exec -- uv run python ops/push-rite.py gert ops/rites/2026-07-10-seed-memory-and-tools.md
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from slop_salon.config import load_config  # noqa: E402
from slop_salon.provision import resolve_secrets  # noqa: E402


def push_rite(name: str, rite_path: str, config_path: str = "slop_salon.toml") -> None:
    body = Path(rite_path).read_text()

    config = load_config(config_path)
    if name not in config.agents:
        raise SystemExit(f"agent {name!r} missing from {config_path}")
    agent = config.agents[name]

    env = resolve_secrets(name, list(config.agents.keys()))
    gh_token = env.get("GH_TOKEN")
    if not gh_token:
        raise SystemExit(
            "GH_TOKEN missing from resolved env; "
            "check ~/.config/mise/config.local.toml for SLOP_GH_TOKEN"
        )
    push_env = {**os.environ, "GH_TOKEN": gh_token}

    with tempfile.TemporaryDirectory() as tmp:
        clone_dir = Path(tmp) / "repo"
        subprocess.run(
            ["gh", "repo", "clone", agent.github_repo, str(clone_dir), "--", "--depth=1"],
            check=True,
            capture_output=True,
            env=push_env,
        )
        target = clone_dir / "RITE.md"
        if target.exists():
            raise SystemExit(
                f"{name}: RITE.md already present (an unperformed rite); refusing to overwrite. "
                "Wait for the agent to perform and delete it, or remove it deliberately."
            )
        target.write_text(body)
        subprocess.run(["git", "add", "RITE.md"], cwd=clone_dir, check=True)
        subprocess.run(
            ["git", "commit", "-m", f"Rite: {Path(rite_path).stem}"],
            cwd=clone_dir,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "push"],
            cwd=clone_dir,
            check=True,
            capture_output=True,
            env=push_env,
        )
        print(f"{name}: pushed RITE.md ({Path(rite_path).name})")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(f"usage: {sys.argv[0]} <agent-name> <rite-path>")
    push_rite(sys.argv[1], sys.argv[2])
