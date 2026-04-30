"""Bluesky CLI tools for slop-studio agents.

Each command is exposed as a separate typer app via [project.scripts].
All commands read BSKY_HANDLE and BSKY_PASSWORD from env.
"""

from __future__ import annotations

import os
from pathlib import Path

import typer
from atproto import Client


def _get_client() -> Client:
    """Authenticate against Bluesky using env-var credentials."""
    handle = os.environ.get("BSKY_HANDLE")
    password = os.environ.get("BSKY_PASSWORD")
    if not handle:
        typer.echo("error: BSKY_HANDLE env var is required", err=True)
        raise typer.Exit(code=1)
    if not password:
        typer.echo("error: BSKY_PASSWORD env var is required", err=True)
        raise typer.Exit(code=1)
    client = Client()
    client.login(handle, password)
    return client


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

    if len(images) > 4:
        typer.echo("error: at most 4 images per post (Bluesky limit)", err=True)
        raise typer.Exit(code=1)
    if images and len(alts) != len(images):
        typer.echo(
            "error: each --image needs a matching --alt (alt text is mandatory)",
            err=True,
        )
        raise typer.Exit(code=1)

    client = _get_client()

    embed = None
    if images:
        uploaded = []
        for path, alt_text in zip(images, alts, strict=True):
            blob = client.upload_blob(path.read_bytes()).blob
            uploaded.append({"alt": alt_text, "image": blob})
        embed = {"$type": "app.bsky.embed.images", "images": uploaded}
    elif video:
        blob = client.upload_blob(video.read_bytes()).blob
        embed = {"$type": "app.bsky.embed.video", "video": blob}

    if embed:
        client.send_post(text=text, embed=embed)
    else:
        client.send_post(text=text)
    typer.echo("posted")


# --- bsky-reply ---

reply_app = typer.Typer(add_completion=False, help="Reply in an existing Bluesky thread.")


def _build_reply_ref(client: Client, parent_uri: str) -> dict:
    """Look up a parent post and build the reply ref structure (parent + root)."""
    posts = client.get_posts([parent_uri]).posts
    if not posts:
        typer.echo(f"error: parent post not found: {parent_uri}", err=True)
        raise typer.Exit(code=1)
    parent = posts[0]
    parent_ref = {"uri": parent.uri, "cid": parent.cid}
    # If parent is itself a reply, root traces back to parent.record.reply.root.
    # Otherwise, parent IS the root.
    existing_reply = getattr(parent.record, "reply", None)
    root_ref = existing_reply.root if existing_reply else parent_ref
    if not isinstance(root_ref, dict):
        root_ref = {"uri": root_ref.uri, "cid": root_ref.cid}
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
    if len(images) > 4:
        typer.echo("error: at most 4 images per post", err=True)
        raise typer.Exit(code=1)
    if images and len(alts) != len(images):
        typer.echo("error: each --image needs a matching --alt", err=True)
        raise typer.Exit(code=1)

    client = _get_client()
    reply_ref = _build_reply_ref(client, parent)

    embed = None
    if images:
        uploaded = []
        for path, alt_text in zip(images, alts, strict=True):
            blob = client.upload_blob(path.read_bytes()).blob
            uploaded.append({"alt": alt_text, "image": blob})
        embed = {"$type": "app.bsky.embed.images", "images": uploaded}

    kwargs = {"text": text, "reply": reply_ref}
    if embed:
        kwargs["embed"] = embed
    client.send_post(**kwargs)
    typer.echo("replied")


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
    if len(images) > 4:
        typer.echo("error: at most 4 images per post", err=True)
        raise typer.Exit(code=1)
    if images and len(alts) != len(images):
        typer.echo("error: each --image needs a matching --alt", err=True)
        raise typer.Exit(code=1)

    client = _get_client()
    posts = client.get_posts([quoted]).posts
    if not posts:
        typer.echo(f"error: quoted post not found: {quoted}", err=True)
        raise typer.Exit(code=1)
    quoted_ref = {"uri": posts[0].uri, "cid": posts[0].cid}

    if images:
        uploaded = []
        for path, alt_text in zip(images, alts, strict=True):
            blob = client.upload_blob(path.read_bytes()).blob
            uploaded.append({"alt": alt_text, "image": blob})
        embed = {
            "$type": "app.bsky.embed.recordWithMedia",
            "record": {"$type": "app.bsky.embed.record", "record": quoted_ref},
            "media": {"$type": "app.bsky.embed.images", "images": uploaded},
        }
    else:
        embed = {"$type": "app.bsky.embed.record", "record": quoted_ref}

    client.send_post(text=text, embed=embed)
    typer.echo("quoted")


# --- bsky-read-timeline ---

read_timeline_app = typer.Typer(
    add_completion=False, help="Read your home feed (or another actor's feed) as JSON."
)


def _dump_feed(feed_view) -> list[dict]:
    """Serialise a list of FeedViewPost to JSON-safe plain dicts.

    `mode="json"` coerces non-JSON-native values (datetime, etc.) to strings;
    without it, json.dumps would fail on real atproto responses.
    """
    return [item.model_dump(mode="json", exclude_none=True) for item in feed_view]


@read_timeline_app.command()
def read_timeline(
    actor: str = typer.Option(None, "--actor", help="Handle of an actor (default: your home feed)"),
    limit: int = typer.Option(20, "--limit", help="Number of posts to return"),
):
    """Print recent feed posts as JSON to stdout."""
    import json

    client = _get_client()
    if actor:
        response = client.get_author_feed(actor=actor, limit=limit)
    else:
        response = client.get_timeline(limit=limit)
    typer.echo(json.dumps(_dump_feed(response.feed), indent=2))
