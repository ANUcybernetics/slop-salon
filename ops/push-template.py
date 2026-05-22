"""Push a re-rendered template file from this admin repo into one live agent's GH repo.

Use when an admin-side template (`templates/CLAUDE.md`, `templates/SIBLINGS.md`,
`templates/slop-tick`, or `SOUL.md`) has been edited and you want the change
to flow to a live agent without re-provisioning.

`_build_template_files` re-renders all templates with the agent's
name/handle/siblings substituted; this script writes one of them to the
agent's GH repo, commits, and pushes. The next tick's `git pull --rebase`
inside the sprite picks it up.

WARNING: this overwrites the file in the agent's repo. Run `slop drift -f
<file>` first --- if the agent has drifted from the template, this will lose
their edits. See `.claude/commands/rollout.md` for the full workflow.

Run from the project root:

    mise exec -- uv run python ops/push-template.py <agent-name> <filename>

Examples:

    mise exec -- uv run python ops/push-template.py lou CLAUDE.md
    mise exec -- uv run python ops/push-template.py lou slop-tick
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from slop_salon.config import load_config  # noqa: E402
from slop_salon.provision import _build_template_files, resolve_secrets  # noqa: E402


def push_template(name: str, filename: str, config_path: str = "slop_salon.toml") -> None:
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

    siblings = [(s, config.agents[s].handle) for s in agent.siblings if s in config.agents]
    files = _build_template_files(
        Path("templates"),
        Path("SOUL.md"),
        agent.name,
        agent.handle,
        siblings,
    )
    if filename not in files:
        raise SystemExit(f"no template renders to {filename!r}; have {sorted(files)}")
    rendered = files[filename]

    with tempfile.TemporaryDirectory() as tmp:
        clone_dir = Path(tmp) / "repo"
        subprocess.run(
            ["gh", "repo", "clone", agent.github_repo, str(clone_dir), "--", "--depth=1"],
            check=True,
            capture_output=True,
            env=push_env,
        )
        target = clone_dir / filename
        if target.exists() and target.read_text() == rendered:
            print(f"{name}: {filename} already matches template, skipping")
            return
        target.write_text(rendered)
        subprocess.run(["git", "add", filename], cwd=clone_dir, check=True)
        result = subprocess.run(
            ["git", "commit", "-m", f"Sync {filename} from admin templates"],
            cwd=clone_dir,
            capture_output=True,
        )
        if result.returncode != 0:
            print(f"{name}: {filename} unchanged (no commit)")
            return
        subprocess.run(
            ["git", "push"],
            cwd=clone_dir,
            check=True,
            capture_output=True,
            env=push_env,
        )
        print(f"{name}: pushed {filename}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(f"usage: {sys.argv[0]} <agent-name> <filename>")
    push_template(sys.argv[1], sys.argv[2])
