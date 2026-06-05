"""Thin CLI wrapper around `slop_salon.recreate` (see that module's docstring).

Use when an agent's sprite VM is wedged (the wake driver reports `i/o timeout`
to the sprite proxy for ~165s on every tick) but the agent's GitHub repo still
holds the source of truth for its accumulated work.

Run from the project root:

    mise exec -- uv run python ops/recreate-sprite.py <name>

The wake driver self-heals wedged sprites automatically (see
`slop_salon.healing`); this script is for manual / one-off recovery.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from slop_salon.recreate import recreate  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} <agent-name>")
    name = sys.argv[1]
    recreate(name)
    print("\nSmoke-test with:")
    print(f'  mise exec -- uv run slop talk {name} "Smoke test --- one sentence, no posting."')
