"""Bluesky CLI tools for slop-studio agents.

Each command is exposed as a separate typer app via [project.scripts].
All commands read BSKY_HANDLE and BSKY_PASSWORD from env.
"""
from __future__ import annotations

import os
import sys
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
):
    """Post plain text to Bluesky."""
    client = _get_client()
    client.send_post(text=text)
    typer.echo("posted")
