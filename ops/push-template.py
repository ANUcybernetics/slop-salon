"""Push one re-rendered template file into a live agent's GitHub repo.

For a fix to `slop-tick`, `setup.sh` or `.gitignore` that has to reach a
running agent without a season reset. The next tick's `git pull --rebase`
picks it up. It overwrites the file: run `slop drift -f <file>` first, since
an agent that has edited `CLAUDE.md` or `setup.sh` would lose its edits.

    mise exec -- uv run python ops/push-template.py <agent> <file>
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from slop_salon.config import load_config
from slop_salon.github_push import put_file
from slop_salon.provision import build_template_files


def push_template(name: str, filename: str, config_path: str = "slop_salon.toml") -> None:
    config = load_config(config_path)
    if name not in config.agents:
        raise SystemExit(f"agent {name!r} missing from {config_path}")
    agent = config.agents[name]
    token = os.environ.get("SLOP_GH_TOKEN")
    if not token:
        raise SystemExit("SLOP_GH_TOKEN is not set (~/.config/mise/config.local.toml)")
    files = build_template_files(config, agent)
    if filename not in files:
        raise SystemExit(f"no template renders to {filename!r}; have {sorted(files)}")
    outcome = put_file(
        agent.github_repo,
        filename,
        files[filename],
        f"Sync {filename} from admin templates",
        {**os.environ, "GH_TOKEN": token},
    )
    print(f"{name}: {outcome} {filename}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(f"usage: {sys.argv[0]} <agent> <file>")
    push_template(sys.argv[1], sys.argv[2])
