"""Reset an agent to a fresh season start, keeping its sprite and accounts.

Four moves, in order:

1. tag the repo head (`season-N`) on GitHub, so nothing is lost, only moved;
2. force-push an orphan commit of freshly interpolated templates and the
   agent's soul, so `git log` in the sprite starts at one commit;
3. recreate the sprite from that branch;
4. Bluesky hygiene from the admin box: unfollow everyone, follow the siblings
   (the home feed is the salon), blank the profile, assert the `bot`
   self-label, mark every notification seen, and post a pinned season marker.

The unfollow, the follow and the seen-mark are what close the salon: without
them every salon is cross-contaminated on tick one (the first season-2 wake
proved it for notifications). The label is asserted rather than merged because
a profile write is exactly how three season-1 agents lost theirs.
"""

from __future__ import annotations

import datetime as dt
import subprocess
import tempfile
from pathlib import Path

import httpx

from .config import load_config
from .provision import build_template_files, write_files
from .recreate import recreate
from .sprites import SpriteExecutor, SpritesClient
from .tools.bsky import DEFAULT_TIMEOUT, Session, create_session

SEASON = 2
RESET_COMMIT_MESSAGE = f"Season {SEASON}: fresh start"
MARKER_TEXT = (
    f"season {SEASON} starts here. everything before this post is an earlier season, "
    "kept as it was."
)

FOLLOW_COLLECTION = "app.bsky.graph.follow"
POST_COLLECTION = "app.bsky.feed.post"
PROFILE_COLLECTION = "app.bsky.actor.profile"
BOT_SELF_LABELS = {
    "$type": "com.atproto.label.defs#selfLabels",
    "values": [{"val": "bot"}],
}
# The PDS shards answer in well under a second, but one reset saw a 20s read
# timeout on a routine call; be patient rather than clever.
BLUESKY_TIMEOUT = 3 * DEFAULT_TIMEOUT


def build_reset_profile(existing: dict | None, pinned: dict | None = None) -> dict:
    """A blank-slate profile that still says `bot`. Only `createdAt` survives
    (the app writes it at signup); `pinned` is the season marker's strong ref."""
    record: dict = {"$type": PROFILE_COLLECTION, "labels": BOT_SELF_LABELS}
    if existing and "createdAt" in existing:
        record["createdAt"] = existing["createdAt"]
    if pinned:
        record["pinnedPost"] = {"uri": pinned["uri"], "cid": pinned["cid"]}
    return record


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def push_season_reset(remote: str, files: dict[str, str], tag: str) -> str:
    """Tag the remote's head `tag`, then replace its default branch with one
    orphan commit containing exactly `files`. Returns the branch pushed.

    Idempotent on the tag: an existing `tag` is left where it is, so a retry
    cannot move the old-season marker onto the reset commit.
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
        write_files(clone, files)
        _git(["add", "-A"], cwd=clone)
        _git(["commit", "--quiet", "-m", RESET_COMMIT_MESSAGE], cwd=clone)
        _git(["push", "--quiet", "--force", "origin", f"HEAD:refs/heads/{branch}"], cwd=clone)
        return branch


def _xrpc(client: httpx.Client, method: str, nsid: str, **kwargs) -> dict:
    resp = client.request(method, f"/xrpc/{nsid}", **kwargs)
    if resp.status_code != 200:
        raise RuntimeError(f"{nsid} returned {resp.status_code}: {resp.text}")
    return resp.json() if resp.content else {}


def _now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def list_follow_rkeys(client: httpx.Client, did: str) -> list[str]:
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


def follow(client: httpx.Client, did: str, handle: str) -> None:
    subject = _xrpc(client, "GET", "com.atproto.identity.resolveHandle", params={"handle": handle})
    _xrpc(
        client,
        "POST",
        "com.atproto.repo.createRecord",
        json={
            "repo": did,
            "collection": FOLLOW_COLLECTION,
            "record": {
                "$type": FOLLOW_COLLECTION,
                "subject": subject["did"],
                "createdAt": _now_iso(),
            },
        },
    )


def post_season_marker(client: httpx.Client, did: str, text: str = MARKER_TEXT) -> dict:
    """Post `text` under the agent's name and return its strong ref. On retry an
    existing marker among recent posts is returned rather than duplicated."""
    feed = _xrpc(
        client,
        "GET",
        "app.bsky.feed.getAuthorFeed",
        params={"actor": did, "limit": "30", "filter": "posts_no_replies"},
    )
    for item in feed.get("feed") or []:
        post = item.get("post") or {}
        if (post.get("record") or {}).get("text") == text:
            return {"uri": post["uri"], "cid": post["cid"]}
    created = _xrpc(
        client,
        "POST",
        "com.atproto.repo.createRecord",
        json={
            "repo": did,
            "collection": POST_COLLECTION,
            "record": {"$type": POST_COLLECTION, "text": text, "createdAt": _now_iso()},
        },
    )
    return {"uri": created["uri"], "cid": created["cid"]}


def reset_bluesky(session: Session, siblings: list[str], marker: bool = True) -> dict:
    """Unfollow everyone, follow `siblings`, post and pin the season marker,
    rewrite the profile as `build_reset_profile`, and mark every notification
    seen so the routine's unread filter starts now."""
    with httpx.Client(
        base_url=session.pds, headers=session.auth_headers, timeout=BLUESKY_TIMEOUT
    ) as client:
        rkeys = list_follow_rkeys(client, session.did)
        for rkey in rkeys:
            _xrpc(
                client,
                "POST",
                "com.atproto.repo.deleteRecord",
                json={"repo": session.did, "collection": FOLLOW_COLLECTION, "rkey": rkey},
            )
        for handle in siblings:
            follow(client, session.did, handle)

        pinned = post_season_marker(client, session.did) if marker else None

        resp = client.get(
            "/xrpc/com.atproto.repo.getRecord",
            params={"repo": session.did, "collection": PROFILE_COLLECTION, "rkey": "self"},
        )
        existing = resp.json().get("value") if resp.status_code == 200 else None
        record = build_reset_profile(existing, pinned)
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
        seen_at = _now_iso()
        _xrpc(client, "POST", "app.bsky.notification.updateSeen", json={"seenAt": seen_at})
    return {
        "unfollowed": len(rkeys),
        "followed": list(siblings),
        "profile": record,
        "seen_at": seen_at,
    }


def _sprite_sh(sprites: SpriteExecutor, sprite_id: str, script: str):
    return sprites.exec(sprite_id, ["bash", "-lc", script])


def preflight_sprite(sprites: SpriteExecutor, sprite_id: str, repo_dir: str, strict: bool) -> None:
    """Refuse a sprite mid-tick; with `strict`, also one holding unpushed commits
    (the tag would miss them)."""
    running = _sprite_sh(
        sprites, sprite_id, "pgrep -f '[c]laude -p' || pgrep -f '[c]laude --print' || true"
    )
    if running.stdout.strip():
        raise SystemExit(f"{sprite_id}: a tick is running; wait for it before resetting")
    if not strict:
        return
    unpushed = _sprite_sh(
        sprites,
        sprite_id,
        f"cd {repo_dir} && git fetch --quiet && git log --oneline @{{u}}..HEAD 2>/dev/null | wc -l",
    )
    if unpushed.exit_code != 0 or unpushed.stdout.strip() not in ("", "0"):
        raise SystemExit(
            f"{sprite_id}: unpushed commits or an unreadable repo ({unpushed.stdout.strip()!r}); "
            "push or pass --discard-unpushed"
        )


def reset(
    name: str,
    config_path: str | Path = "slop_salon.toml",
    templates_dir: str | Path = "templates",
    souls_dir: str | Path = "souls",
    sprites: SpritesClient | None = None,
    tag: str = f"season-{SEASON - 1}",
    skip_repo: bool = False,
    skip_sprite: bool = False,
    skip_bluesky: bool = False,
    marker: bool = True,
    discard_unpushed: bool = False,
) -> None:
    """Reset agent `name` to a fresh season start (module docstring).

    Everything that can fail on the admin box is checked before the first
    destructive step. The `skip_*` flags make a part-way failure retryable;
    the orphan push is the one step not safe to repeat once the sprite has
    cloned it, so a retry after a Bluesky timeout is `--skip-repo --skip-sprite`.
    """
    from .tick import tick_env

    config = load_config(config_path)
    if name not in config.agents:
        raise SystemExit(f"agent {name!r} missing from {config_path}")
    agent = config.agents[name]
    env = tick_env(config, agent)
    salon_provider = config.salons[agent.salon].provider if agent.salon else ""
    if agent.provider and agent.provider != salon_provider:
        print(f"note: {name} carries a provider override ({agent.provider!r}); delete it if wrong")

    session: Session | None = None
    if skip_bluesky:
        print("[1/5] Skipping Bluesky (--skip-bluesky)")
    else:
        print(f"[1/5] Opening Bluesky session as {agent.handle}")
        session = create_session(agent.handle, env["BSKY_PASSWORD"])

    sprites = sprites or SpritesClient()
    if skip_sprite:
        print("[2/5] Skipping sprite pre-flight (--skip-sprite)")
    else:
        if not agent.sprite_id:
            raise SystemExit(f"{name} has no sprite_id; use `slop new`, not a reset")
        print(f"[2/5] Pre-flighting sprite {agent.sprite_id!r}")
        preflight_sprite(
            sprites, agent.sprite_id, f"~/slop-salon-{name}", strict=not discard_unpushed
        )

    if skip_repo:
        print("[3/5] Skipping tag + orphan push (--skip-repo)")
    else:
        print(f"[3/5] Tagging {agent.github_repo} head as {tag}, pushing an orphan reset commit")
        files = build_template_files(config, agent, templates_dir, souls_dir)
        remote = f"https://{env['GH_TOKEN']}@github.com/{agent.github_repo}.git"
        branch = push_season_reset(remote, files, tag=tag)
        print(f"  -> {branch} is now one commit; {tag} holds the old head")

    if skip_sprite:
        print("[4/5] Skipping sprite recreate (--skip-sprite)")
    else:
        print("[4/5] Recreating sprite")
        recreate(name, config_path=str(config_path), sprites=sprites)

    if session is None:
        print("[5/5] Skipping Bluesky hygiene (--skip-bluesky)")
    else:
        siblings = [config.agents[s].handle for s in agent.siblings]
        print("[5/5] Bluesky: unfollow all, follow siblings, blank profile, bot label, mark seen")
        summary = reset_bluesky(session, siblings, marker=marker)
        print(
            f"  -> unfollowed {summary['unfollowed']}, followed {summary['followed']}; "
            f"notifications seen to {summary['seen_at']}"
        )

    print(
        f"\nReset {name}: season {SEASON} on {config.provider_for(name).name}, soul {agent.soul}."
    )
