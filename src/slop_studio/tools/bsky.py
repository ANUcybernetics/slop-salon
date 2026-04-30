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
