"""Thin CLI wrapper around `slop_salon.strip_assets` (see that module's docstring).

One-time history rewrite that drops committed `assets/` media from an agent
repo and force-pushes, then resets the sprite onto the rewritten history. This
reclaims the existing bloat that `templates/.gitignore` only prevents going
forward (task-11).

STOP THE WAKE TIMER FIRST:

    systemctl --user stop slop-wake.timer

then run from the project root:

    mise exec -- uv run python ops/strip-assets.py <name>            # rewrite + reset
    mise exec -- uv run python ops/strip-assets.py <name> --dry-run  # measure only, no push
    mise exec -- uv run python ops/strip-assets.py <name> --no-reset # push, leave sprite

and restart it when done:

    systemctl --user start slop-wake.timer
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from slop_salon.strip_assets import strip_assets  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", help="agent name (as in slop_salon.toml)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="mirror-clone and measure the reduction, but do not push or reset",
    )
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="rewrite and force-push, but do not reset the sprite (do it yourself)",
    )
    args = parser.parse_args()
    strip_assets(args.name, dry_run=args.dry_run, do_reset=not args.no_reset)
