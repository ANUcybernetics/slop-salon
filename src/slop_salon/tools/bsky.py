"""Bluesky CLI tools for slop-salon agents.

Each command is exposed as a separate typer app via [project.scripts].
All commands read BSKY_HANDLE and BSKY_PASSWORD from env.

We talk to the ATProto XRPC API directly (no Python SDK). The atproto
SDK's `Client.login()` follows up createSession with an unconditional
`app.bsky.actor.get_profile` call against AppView; that call hangs for
hours when AppView hasn't reindexed a freshly-changed handle, making
every tool unusable for new agents. Direct HTTP gives us exactly the
calls Bluesky's docs describe — and tests can assert at the wire level.
"""

from __future__ import annotations

import json
import mimetypes
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
import typer

DEFAULT_PDS = "https://bsky.social"
DEFAULT_LANG = "en"
DEFAULT_TIMEOUT = 20.0
UPLOAD_TIMEOUT = 60.0


@dataclass(frozen=True)
class Session:
    did: str
    handle: str
    access_jwt: str
    pds: str

    @property
    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_jwt}"}


def _xrpc_error(resp: httpx.Response, endpoint: str) -> None:
    """Print an XRPC error and exit. Bluesky returns JSON {error, message} on failure."""
    try:
        body = resp.json()
        detail = f"{body.get('error', '?')}: {body.get('message', resp.text)}"
    except ValueError:
        detail = resp.text
    typer.echo(f"error: {endpoint} returned {resp.status_code}: {detail}", err=True)
    raise typer.Exit(code=1)


def _get_session() -> Session:
    """Authenticate against bsky.social and point future calls at the user's real PDS.

    bsky.social is the auth entry point; the actual PDS endpoint (where the
    repo lives) is in the returned didDoc's `AtprotoPersonalDataServer`
    service entry. For accounts on bsky.social's hosting fleet, that's
    typically `https://<shard>.us-west.host.bsky.network`.
    """
    handle = os.environ.get("BSKY_HANDLE")
    password = os.environ.get("BSKY_PASSWORD")
    if not handle:
        typer.echo("error: BSKY_HANDLE env var is required", err=True)
        raise typer.Exit(code=1)
    if not password:
        typer.echo("error: BSKY_PASSWORD env var is required", err=True)
        raise typer.Exit(code=1)
    resp = httpx.post(
        f"{DEFAULT_PDS}/xrpc/com.atproto.server.createSession",
        json={"identifier": handle, "password": password},
        timeout=DEFAULT_TIMEOUT,
    )
    if resp.status_code != 200:
        _xrpc_error(resp, "createSession")
    data = resp.json()
    pds = DEFAULT_PDS
    for svc in data.get("didDoc", {}).get("service") or []:
        if svc.get("type") == "AtprotoPersonalDataServer":
            pds = svc["serviceEndpoint"]
            break
    return Session(
        did=data["did"], handle=data["handle"], access_jwt=data["accessJwt"], pds=pds
    )


def _now_iso() -> str:
    """ISO 8601 timestamp with ms precision and trailing Z (Bluesky's createdAt format)."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _mime_of(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


def _upload_blob(session: Session, path: Path) -> dict:
    """Upload a blob to the user's PDS. Returns the BlobRef the embed needs."""
    resp = httpx.post(
        f"{session.pds}/xrpc/com.atproto.repo.uploadBlob",
        headers={**session.auth_headers, "Content-Type": _mime_of(path)},
        content=path.read_bytes(),
        timeout=UPLOAD_TIMEOUT,
    )
    if resp.status_code != 200:
        _xrpc_error(resp, "uploadBlob")
    return resp.json()["blob"]


def _get_posts(session: Session, uris: list[str]) -> list[dict]:
    """Look up posts by AT URI (used to build reply/quote refs)."""
    resp = httpx.get(
        f"{session.pds}/xrpc/app.bsky.feed.getPosts",
        params={"uris": uris},
        headers=session.auth_headers,
        timeout=DEFAULT_TIMEOUT,
    )
    if resp.status_code != 200:
        _xrpc_error(resp, "getPosts")
    return resp.json().get("posts", [])


def _create_post_record(session: Session, record: dict) -> dict:
    """Create an app.bsky.feed.post record on the user's repo. Returns {uri, cid}."""
    resp = httpx.post(
        f"{session.pds}/xrpc/com.atproto.repo.createRecord",
        headers=session.auth_headers,
        json={
            "repo": session.did,
            "collection": "app.bsky.feed.post",
            "record": record,
        },
        timeout=DEFAULT_TIMEOUT,
    )
    if resp.status_code != 200:
        _xrpc_error(resp, "createRecord")
    return resp.json()


def _validate_media_args(images: list, alts: list) -> None:
    if len(images) > 4:
        typer.echo("error: at most 4 images per post (Bluesky limit)", err=True)
        raise typer.Exit(code=1)
    if images and len(alts) != len(images):
        typer.echo(
            "error: each --image needs a matching --alt (alt text is mandatory)",
            err=True,
        )
        raise typer.Exit(code=1)


def _build_image_embed(session: Session, images: list[Path], alts: list[str]) -> dict:
    uploaded = [
        {"alt": alt_text, "image": _upload_blob(session, path)}
        for path, alt_text in zip(images, alts, strict=True)
    ]
    return {"$type": "app.bsky.embed.images", "images": uploaded}


def _build_video_embed(session: Session, video: Path) -> dict:
    return {"$type": "app.bsky.embed.video", "video": _upload_blob(session, video)}


def _base_post_record(text: str) -> dict:
    return {
        "$type": "app.bsky.feed.post",
        "text": text,
        "createdAt": _now_iso(),
        "langs": [DEFAULT_LANG],
    }


# --- bsky-post ---

post_app = typer.Typer(add_completion=False, help="Post to your own Bluesky account.")


@post_app.command()
def post(
    text: str = typer.Option(..., "--text", help="Post text"),
    image: list[Path] = typer.Option(
        None, "--image", help="Path to image file (up to 4); pair each with --alt"
    ),
    alt: list[str] = typer.Option(None, "--alt", help="Alt text for each --image, in order"),
    video: Path = typer.Option(
        None, "--video", help="Path to mp4 video (single, up to ~60s, ~50MB)"
    ),
):
    """Post text + optional media to Bluesky."""
    images = image or []
    alts = alt or []
    _validate_media_args(images, alts)

    session = _get_session()
    record = _base_post_record(text)
    if images:
        record["embed"] = _build_image_embed(session, images, alts)
    elif video:
        record["embed"] = _build_video_embed(session, video)
    result = _create_post_record(session, record)
    typer.echo(f"posted {result['uri']}")


# --- bsky-reply ---

reply_app = typer.Typer(add_completion=False, help="Reply in an existing Bluesky thread.")


def _build_reply_ref(session: Session, parent_uri: str) -> dict:
    """Look up a parent post and build the reply ref structure (parent + root)."""
    posts = _get_posts(session, [parent_uri])
    if not posts:
        typer.echo(f"error: parent post not found: {parent_uri}", err=True)
        raise typer.Exit(code=1)
    parent = posts[0]
    parent_ref = {"uri": parent["uri"], "cid": parent["cid"]}
    # If parent is itself a reply, the root traces back via parent.record.reply.root.
    # Otherwise, parent IS the root.
    existing_reply = parent.get("record", {}).get("reply")
    root_ref = existing_reply["root"] if existing_reply else parent_ref
    return {"parent": parent_ref, "root": root_ref}


@reply_app.command()
def reply(
    parent: str = typer.Option(..., "--parent", help="at:// URI of the post to reply to"),
    text: str = typer.Option(..., "--text", help="Reply text"),
    image: list[Path] = typer.Option(None, "--image", help="Up to 4 images; pair with --alt"),
    alt: list[str] = typer.Option(None, "--alt", help="Alt text for each --image"),
):
    """Reply to a Bluesky post."""
    images = image or []
    alts = alt or []
    _validate_media_args(images, alts)

    session = _get_session()
    record = _base_post_record(text)
    record["reply"] = _build_reply_ref(session, parent)
    if images:
        record["embed"] = _build_image_embed(session, images, alts)
    result = _create_post_record(session, record)
    typer.echo(f"replied {result['uri']}")


# --- bsky-quote-post ---

quote_post_app = typer.Typer(
    add_completion=False, help="Post that quotes another post, with commentary."
)


@quote_post_app.command()
def quote_post(
    quoted: str = typer.Option(..., "--quoted", help="at:// URI of the post being quoted"),
    text: str = typer.Option(..., "--text", help="Your commentary"),
    image: list[Path] = typer.Option(None, "--image", help="Up to 4 images"),
    alt: list[str] = typer.Option(None, "--alt", help="Alt text for each --image"),
):
    """Post an original that quotes another post."""
    images = image or []
    alts = alt or []
    _validate_media_args(images, alts)

    session = _get_session()
    posts = _get_posts(session, [quoted])
    if not posts:
        typer.echo(f"error: quoted post not found: {quoted}", err=True)
        raise typer.Exit(code=1)
    quoted_ref = {"uri": posts[0]["uri"], "cid": posts[0]["cid"]}

    record = _base_post_record(text)
    if images:
        uploaded = [
            {"alt": alt_text, "image": _upload_blob(session, path)}
            for path, alt_text in zip(images, alts, strict=True)
        ]
        record["embed"] = {
            "$type": "app.bsky.embed.recordWithMedia",
            "record": {"$type": "app.bsky.embed.record", "record": quoted_ref},
            "media": {"$type": "app.bsky.embed.images", "images": uploaded},
        }
    else:
        record["embed"] = {"$type": "app.bsky.embed.record", "record": quoted_ref}
    result = _create_post_record(session, record)
    typer.echo(f"quoted {result['uri']}")


# --- bsky-follow ---

follow_app = typer.Typer(add_completion=False, help="Follow another Bluesky account by handle.")


def _resolve_handle(session: Session, handle: str) -> str:
    """Resolve a handle to a DID via the PDS. Hits the PDS, not AppView, so works
    even when AppView hasn't reindexed a recently-changed handle."""
    resp = httpx.get(
        f"{session.pds}/xrpc/com.atproto.identity.resolveHandle",
        params={"handle": handle},
        headers=session.auth_headers,
        timeout=DEFAULT_TIMEOUT,
    )
    if resp.status_code != 200:
        _xrpc_error(resp, "resolveHandle")
    return resp.json()["did"]


@follow_app.command()
def follow(
    handle: str = typer.Option(..., "--handle", help="Handle to follow, e.g. mina.slopsalon.art"),
):
    """Follow another account. Idempotent only at the API level — Bluesky
    won't refuse a duplicate follow but will create a second record. Don't
    spam it."""
    session = _get_session()
    subject_did = _resolve_handle(session, handle)
    resp = httpx.post(
        f"{session.pds}/xrpc/com.atproto.repo.createRecord",
        headers=session.auth_headers,
        json={
            "repo": session.did,
            "collection": "app.bsky.graph.follow",
            "record": {
                "$type": "app.bsky.graph.follow",
                "subject": subject_did,
                "createdAt": _now_iso(),
            },
        },
        timeout=DEFAULT_TIMEOUT,
    )
    if resp.status_code != 200:
        _xrpc_error(resp, "createRecord (follow)")
    typer.echo(f"followed {handle} ({subject_did}) at {resp.json()['uri']}")


# --- bsky-unfollow ---

unfollow_app = typer.Typer(add_completion=False, help="Unfollow an account by handle.")


def _find_follow_rkey(session: Session, subject_did: str) -> str | None:
    """Find the rkey of the user's follow record for subject_did, or None if not following.

    Uses com.atproto.repo.listRecords on the user's own repo (PDS-side, so
    immune to AppView lag). Walks pagination because an agent following
    hundreds of accounts has more than one page of follow records.
    """
    cursor: str | None = None
    while True:
        params: dict[str, str | int] = {
            "repo": session.did,
            "collection": "app.bsky.graph.follow",
            "limit": 100,
        }
        if cursor:
            params["cursor"] = cursor
        resp = httpx.get(
            f"{session.pds}/xrpc/com.atproto.repo.listRecords",
            params=params,
            headers=session.auth_headers,
            timeout=DEFAULT_TIMEOUT,
        )
        if resp.status_code != 200:
            _xrpc_error(resp, "listRecords")
        data = resp.json()
        for rec in data.get("records", []):
            if rec.get("value", {}).get("subject") == subject_did:
                # uri is at://<did>/app.bsky.graph.follow/<rkey>
                return rec["uri"].rsplit("/", 1)[-1]
        cursor = data.get("cursor")
        if not cursor:
            return None


@unfollow_app.command()
def unfollow(
    handle: str = typer.Option(..., "--handle", help="Handle to unfollow, e.g. bsky.app"),
):
    """Unfollow another account. Idempotent: if you don't follow them, exits 0 with a message."""
    session = _get_session()
    subject_did = _resolve_handle(session, handle)
    rkey = _find_follow_rkey(session, subject_did)
    if rkey is None:
        typer.echo(f"not following {handle}; nothing to do")
        return
    resp = httpx.post(
        f"{session.pds}/xrpc/com.atproto.repo.deleteRecord",
        headers=session.auth_headers,
        json={"repo": session.did, "collection": "app.bsky.graph.follow", "rkey": rkey},
        timeout=DEFAULT_TIMEOUT,
    )
    if resp.status_code != 200:
        _xrpc_error(resp, "deleteRecord (unfollow)")
    typer.echo(f"unfollowed {handle} ({subject_did})")


# --- bsky-read-timeline ---

read_timeline_app = typer.Typer(
    add_completion=False, help="Read your home feed (or another actor's feed) as JSON."
)


@read_timeline_app.command()
def read_timeline(
    actor: str = typer.Option(None, "--actor", help="Handle of an actor (default: your home feed)"),
    limit: int = typer.Option(20, "--limit", help="Number of posts to return"),
):
    """Print recent feed posts as JSON to stdout."""
    session = _get_session()
    if actor:
        url = f"{session.pds}/xrpc/app.bsky.feed.getAuthorFeed"
        params = {"actor": actor, "limit": limit}
    else:
        url = f"{session.pds}/xrpc/app.bsky.feed.getTimeline"
        params = {"limit": limit}
    resp = httpx.get(url, params=params, headers=session.auth_headers, timeout=DEFAULT_TIMEOUT)
    if resp.status_code != 200:
        _xrpc_error(resp, "getTimeline" if not actor else "getAuthorFeed")
    typer.echo(json.dumps(resp.json().get("feed", []), indent=2))


# --- bsky-read-notifications ---

read_notifications_app = typer.Typer(
    add_completion=False,
    help="Read replies, mentions, quotes, and likes on your account as JSON.",
)


@read_notifications_app.command()
def read_notifications(
    limit: int = typer.Option(20, "--limit", help="Number of notifications to return"),
):
    """Print recent notifications as JSON to stdout."""
    session = _get_session()
    resp = httpx.get(
        f"{session.pds}/xrpc/app.bsky.notification.listNotifications",
        params={"limit": limit},
        headers=session.auth_headers,
        timeout=DEFAULT_TIMEOUT,
    )
    if resp.status_code != 200:
        _xrpc_error(resp, "listNotifications")
    typer.echo(json.dumps(resp.json().get("notifications", []), indent=2))
