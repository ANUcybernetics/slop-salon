"""Reset an agent to a fresh season start, keeping its sprite and accounts.

A reset is what neither `slop new` nor `recreate` is: `new` commits templates on
top of whatever history the repo already has, and `recreate` preserves the repo
on purpose. Season 2 (task-17) needs the third thing --- the same GitHub repo,
sprite and Bluesky account, but with the agent's accumulated self erased so it
starts from commit one again on a different model. Four moves, in order:

1. tag the current head `season-1` on GitHub, so nothing is lost, only moved;
2. force-push an orphan commit of freshly interpolated templates to the default
   branch, so `git log` in the sprite starts at one commit with stub
   `SIBLINGS.md` and seed `MEMORY.md` / `TOOLS.md`;
3. recreate the sprite via the ordinary recreate path (which clones that
   branch and installs whatever provider the registry now resolves for it);
4. Bluesky hygiene from the admin box: unfollow everyone, blank the bio, drop
   the avatar, and **assert** the `bot` self-label.

The unfollow is the step that matters most for the experiment: without it every
salon's timeline is cross-contaminated on tick one. The label is asserted, not
merged, because the exact operation this performs (a profile write) is how three
season-1 agents lost theirs.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import httpx

from .config import load_config
from .provision import (
    _build_template_files,
    missing_provider_secrets,
    resolve_secrets,
)
from .recreate import recreate
from .sprites import SpritesClient
from .strip_assets import _preflight_sprite
from .tools.bsky import DEFAULT_TIMEOUT, Session, create_session

SEASON_TAG = "season-1"
RESET_COMMIT_MESSAGE = "Season 2: fresh start"

FOLLOW_COLLECTION = "app.bsky.graph.follow"
PROFILE_COLLECTION = "app.bsky.actor.profile"
BOT_SELF_LABELS = {
    "$type": "com.atproto.label.defs#selfLabels",
    "values": [{"val": "bot"}],
}


def build_reset_profile(existing: dict | None) -> dict:
    """The profile record after a reset: a blank slate that still says `bot`.

    Everything the agent wrote into its self-portrait (avatar, banner, bio,
    display name, pinned post) is dropped. Only `createdAt` survives, because
    the Bluesky app writes it at signup and its absence is the fingerprint of a
    self-authored write --- worth keeping honest. The label is set outright
    rather than carried over from `existing`: a merge only preserves what is
    present at read time, and this is the write that dropped it before.
    """
    record: dict = {"$type": PROFILE_COLLECTION, "labels": BOT_SELF_LABELS}
    if existing and "createdAt" in existing:
        record["createdAt"] = existing["createdAt"]
    return record


def _git(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.stdout


def push_season_reset(
    remote: str,
    files: dict[str, str],
    tag: str = SEASON_TAG,
    message: str = RESET_COMMIT_MESSAGE,
) -> str:
    """Tag the remote's head `tag`, then replace its default branch with one
    orphan commit containing exactly `files`. Returns the branch name pushed.

    Idempotent on the tag: if `tag` already exists on the remote it is left
    where it is, so re-running after a failure part-way cannot move the
    season-1 marker onto the reset commit. The branch push is a force-push by
    design --- the orphan shares no history with what it replaces.
    """
    with tempfile.TemporaryDirectory() as tmp:
        clone = Path(tmp) / "repo"
        _git(["clone", "--quiet", remote, str(clone)], cwd=Path(tmp))
        branch = _git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=clone)
        branch = branch.strip().removeprefix("origin/")

        tagged = _git(["ls-remote", "--tags", "origin", f"refs/tags/{tag}"], cwd=clone).strip()
        if tagged:
            print(f"  tag {tag} already on remote; leaving it where it is")
        else:
            _git(["tag", tag], cwd=clone)
            _git(["push", "--quiet", "origin", f"refs/tags/{tag}"], cwd=clone)

        _git(["checkout", "--quiet", "--orphan", "season-reset"], cwd=clone)
        _git(["rm", "-rfq", "."], cwd=clone)
        _git(["clean", "-fdxq"], cwd=clone)
        for rel_path, content in files.items():
            target = clone / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        _git(["add", "-A"], cwd=clone)
        _git(["commit", "--quiet", "-m", message], cwd=clone)
        _git(["push", "--quiet", "--force", "origin", f"HEAD:refs/heads/{branch}"], cwd=clone)
        return branch


def _xrpc(client: httpx.Client, method: str, nsid: str, **kwargs) -> dict:
    resp = client.request(method, f"/xrpc/{nsid}", **kwargs)
    if resp.status_code != 200:
        raise RuntimeError(f"{nsid} returned {resp.status_code}: {resp.text}")
    return resp.json() if resp.content else {}


def list_follow_rkeys(client: httpx.Client, did: str) -> list[str]:
    """Every `app.bsky.graph.follow` record key in the repo, across pages."""
    rkeys: list[str] = []
    cursor: str | None = None
    while True:
        params: dict[str, str] = {"repo": did, "collection": FOLLOW_COLLECTION, "limit": "100"}
        if cursor:
            params["cursor"] = cursor
        page = _xrpc(client, "GET", "com.atproto.repo.listRecords", params=params)
        rkeys.extend(rec["uri"].rsplit("/", 1)[-1] for rec in page.get("records", []))
        cursor = page.get("cursor")
        if not cursor or not page.get("records"):
            return rkeys


def reset_bluesky(session: Session) -> dict[str, int | dict]:
    """Unfollow everyone and rewrite the profile as `build_reset_profile`."""
    with httpx.Client(
        base_url=session.pds, headers=session.auth_headers, timeout=DEFAULT_TIMEOUT
    ) as client:
        rkeys = list_follow_rkeys(client, session.did)
        for rkey in rkeys:
            _xrpc(
                client,
                "POST",
                "com.atproto.repo.deleteRecord",
                json={"repo": session.did, "collection": FOLLOW_COLLECTION, "rkey": rkey},
            )

        resp = client.get(
            "/xrpc/com.atproto.repo.getRecord",
            params={"repo": session.did, "collection": PROFILE_COLLECTION, "rkey": "self"},
        )
        existing = resp.json().get("value") if resp.status_code == 200 else None
        record = build_reset_profile(existing)
        _xrpc(
            client,
            "POST",
            "com.atproto.repo.putRecord",
            json={
                "repo": session.did,
                "collection": PROFILE_COLLECTION,
                "rkey": "self",
                "record": record,
            },
        )
    return {"unfollowed": len(rkeys), "profile": record}


def reset(
    name: str,
    config_path: str | Path = "slop_salon.toml",
    templates_dir: str | Path = "templates",
    soul_path: str | Path = "SOUL.md",
    sprites: SpritesClient | None = None,
    tag: str = SEASON_TAG,
    skip_sprite: bool = False,
    skip_bluesky: bool = False,
) -> None:
    """Reset agent `name` to a fresh season start. See the module docstring.

    Everything that can fail on the admin box is checked before the first
    destructive step: the provider must resolve with its secrets present, the
    Bluesky password must open a session, and the sprite must be idle with
    nothing unpushed (otherwise the tag would miss work the reset destroys).
    """
    config = load_config(config_path)
    if name not in config.agents:
        raise SystemExit(f"agent {name!r} missing from {config_path}")
    agent = config.agents[name]

    provider = config.provider_for(name)
    missing = missing_provider_secrets(provider)
    if missing:
        raise SystemExit(f"provider {provider.name!r} needs {missing} in the admin env")
    if agent.provider and agent.provider != (
        config.salons[agent.salon].provider if agent.salon else ""
    ):
        print(
            f"note: {name} carries a provider override ({agent.provider!r}); the reset "
            f"installs that, not the salon's --- delete the override first if that is wrong"
        )

    env = resolve_secrets(name, list(config.agents.keys()))
    gh_token = env.get("GH_TOKEN")
    if not gh_token:
        raise SystemExit("missing GH_TOKEN in resolved env; check SLOP_GH_TOKEN")

    session: Session | None = None
    if not skip_bluesky:
        password = env.get("BSKY_PASSWORD")
        if not password:
            raise SystemExit(f"no bsky_password for {name} in secrets.toml")
        print(f"[1/5] Opening Bluesky session as {agent.handle}")
        session = create_session(agent.handle, password)
    else:
        print("[1/5] Skipping Bluesky (--skip-bluesky)")

    sprites = sprites or SpritesClient()
    if not skip_sprite:
        if not agent.sprite_id:
            raise SystemExit(f"{name} has no sprite_id; use `slop new`, not a reset")
        print(f"[2/5] Pre-flighting sprite {agent.sprite_id!r} (idle, nothing unpushed)")
        _preflight_sprite(sprites, agent.sprite_id, f"~/slop-salon-{name}")
    else:
        print("[2/5] Skipping sprite pre-flight (--skip-sprite)")

    print(f"[3/5] Tagging {agent.github_repo} head as {tag} and pushing an orphan reset commit")
    siblings = [(s, config.agents[s].handle) for s in agent.siblings if s in config.agents]
    files = _build_template_files(
        Path(templates_dir), Path(soul_path), agent.name, agent.handle, siblings
    )
    remote = f"https://{gh_token}@github.com/{agent.github_repo}.git"
    branch = push_season_reset(remote, files, tag=tag)
    print(f"  -> {branch} is now one commit; {tag} holds the old head")

    if not skip_sprite:
        print(f"[4/5] Recreating sprite on provider {provider.name!r}")
        recreate(name, config_path=str(config_path), sprites=sprites)
    else:
        print("[4/5] Skipping sprite recreate (--skip-sprite)")

    if session is not None:
        print("[5/5] Bluesky hygiene: unfollow all, blank profile, assert bot label")
        summary = reset_bluesky(session)
        print(f"  -> unfollowed {summary['unfollowed']}; profile is now {summary['profile']}")
    else:
        print("[5/5] Skipping Bluesky hygiene (--skip-bluesky)")

    print(f"\nReset {name}: fresh start on {provider.name}.")
