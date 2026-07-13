"""Strip committed ``assets/`` media from an agent repo's history (task-11).

The agent repos grew to 0.5--1.1 GB from media committed via each tick's
``git add -A``. `templates/.gitignore` now keeps new media out of git, but that
only stops *growth* --- the existing blobs are live in history (the working tree
~= the whole repo), so ``git gc`` cannot reclaim them. This one-time rewrite
drops ``assets/`` from every commit and force-pushes the result, taking each
repo back to a few MB and making a fresh clone (and thus ``recreate-sprite.py``)
reliable again.

Flow, per agent:

1. **Pre-flight the sprite** (unless ``--no-reset``): refuse if a tick is
   running (the in-sprite flock does not protect an out-of-band ``sprite exec``)
   or if the sprite has commits not yet on GitHub. That second check is the
   ``lou`` blind spot --- a push failing on an oversize blob strands local
   commits, and a later ``git reset --hard`` would destroy them. We abort rather
   than rewrite so those commits can be salvaged by hand first.
2. **Rewrite** in a throwaway ``--mirror`` clone with ``git filter-repo``, then
   force-push the stripped history.
3. **Reset the sprite** onto the rewritten history out of band
   (``git fetch && git reset --hard``), *not* via a ``RITE.md``: ``slop-tick``'s
   opening ``git pull --rebase`` would replay the sprite's pre-rewrite commits
   onto the unrelated new history and reintroduce every asset. The reset clears
   the sprite's old tracked ``assets/`` from disk --- accepted, and identical to
   what a recreate does; media is ephemeral workshop by design.

**Stop the wake timer for the duration** (``systemctl --user stop
slop-wake.timer``). A tick that fires between the force-push and the reset would
hit exactly the ``git pull --rebase`` reintroduction above.

Run from the project root:

    mise exec -- uv run python ops/strip-assets.py <name> [--dry-run] [--no-reset]
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from .config import load_config
from .provision import resolve_secrets
from .sprites import SpritesClient


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


def _ensure_filter_repo() -> str:
    """Return a runnable ``git-filter-repo``, installing it via uv if absent."""
    exe = shutil.which("git-filter-repo")
    if exe:
        return exe
    print("git-filter-repo not found --- installing via `uv tool install`")
    subprocess.run(["uv", "tool", "install", "git-filter-repo"], check=True)
    exe = shutil.which("git-filter-repo")
    if not exe:
        raise SystemExit(
            "git-filter-repo still not on PATH after install; "
            "check that ~/.local/bin (uv tool dir) is on PATH"
        )
    return exe


def _dir_size_bytes(path: Path) -> int:
    out = _run(["du", "-sb", str(path)]).stdout
    return int(out.split()[0])


def _human(nbytes: int) -> str:
    size = float(nbytes)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}GiB"


def _sprite_sh(sprites: SpritesClient, name: str, script: str) -> subprocess.CompletedProcess[str]:
    result = sprites.exec(name, ["bash", "-lc", script])
    return subprocess.CompletedProcess(
        args=script, returncode=result.exit_code, stdout=result.stdout, stderr=result.stderr
    )


def _preflight_sprite(sprites: SpritesClient, name: str, repo_dir: str) -> None:
    """Abort unless the sprite is idle and fully pushed to GitHub.

    Fetches first so ``origin/HEAD`` reflects GitHub *before* we rewrite it, then
    counts commits the sprite holds that GitHub does not.
    """
    running = _sprite_sh(sprites, name, "pgrep -f 'claude --print' || true")
    if running.stdout.strip():
        raise SystemExit(
            f"{name}: a tick is running (claude --print live). Stop the wake timer "
            f"and wait for it to finish before rewriting."
        )
    ahead = _sprite_sh(
        sprites,
        name,
        f"cd {repo_dir} && git fetch --quiet origin && git rev-list --count @{{u}}..HEAD",
    )
    if ahead.returncode != 0:
        raise SystemExit(
            f"{name}: could not check for un-pushed commits "
            f"(exit {ahead.returncode}): {ahead.stderr.strip() or ahead.stdout.strip()}"
        )
    count = ahead.stdout.strip()
    if count != "0":
        raise SystemExit(
            f"{name}: sprite has {count} commit(s) not on GitHub. A history rewrite "
            f"+ reset --hard would destroy them. Salvage their non-asset content by "
            f"hand (push what is recoverable), then re-run."
        )


def _detect_branch(mirror: Path) -> str:
    ref = _run(["git", "symbolic-ref", "HEAD"], cwd=mirror).stdout.strip()
    return ref.removeprefix("refs/heads/")


def strip_assets(
    name: str,
    *,
    config_path: str = "slop_salon.toml",
    dry_run: bool = False,
    do_reset: bool = True,
    sprites: SpritesClient | None = None,
) -> None:
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
    repo_url = f"https://{gh_token}@github.com/{agent.github_repo}.git"
    repo_dir = f"~/slop-salon-{name}"

    filter_repo = _ensure_filter_repo()

    if do_reset and not dry_run:
        sprites = sprites or SpritesClient()
        print(f"[{name}] pre-flight: sprite idle + fully pushed")
        _preflight_sprite(sprites, name, repo_dir)

    with tempfile.TemporaryDirectory() as tmp:
        mirror = Path(tmp) / f"{name}.git"
        print(f"[{name}] mirror-cloning (this is the one heavy step)")
        _run(["git", "clone", "--mirror", repo_url, str(mirror)])
        branch = _detect_branch(mirror)
        before = _dir_size_bytes(mirror)

        print(f"[{name}] stripping assets/ from history")
        _run([filter_repo, "--path", "assets/", "--invert-paths", "--force"], cwd=mirror)
        after = _dir_size_bytes(mirror)
        print(f"[{name}] .git {_human(before)} -> {_human(after)} (branch {branch})")

        if dry_run:
            print(f"[{name}] dry-run: not pushing, not resetting")
            return

        # filter-repo removes 'origin' to guard against accidental pushes.
        _run(["git", "remote", "add", "origin", repo_url], cwd=mirror)
        print(f"[{name}] force-pushing rewritten {branch}")
        _run(["git", "push", "--force", "origin", branch], cwd=mirror)

    if not do_reset:
        print(f"[{name}] --no-reset: sprite NOT reset; do it before the wake timer restarts")
        return

    assert sprites is not None
    print(f"[{name}] resetting sprite onto rewritten history")
    reset = _sprite_sh(
        sprites,
        name,
        f"cd {repo_dir} && git fetch --quiet origin && "
        f"git reset --hard origin/{branch} && du -sh .git",
    )
    if reset.returncode != 0:
        raise SystemExit(
            f"{name}: sprite reset failed (exit {reset.returncode}): "
            f"{reset.stderr.strip() or reset.stdout.strip()}"
        )
    print(f"[{name}] sprite .git now: {reset.stdout.strip().splitlines()[-1]}")
    print(f"[{name}] done")
