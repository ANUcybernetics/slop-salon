"""Live Bluesky integration tests.

Marked `integration` so they're skipped by default. Run with:
    uv run pytest -m integration

Use a dedicated test account; these tests post and delete real content.
"""

from __future__ import annotations

import json
import os
import subprocess

import pytest

pytestmark = pytest.mark.integration


def _run_cli(command: str, *args: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    """Invoke an installed CLI entry point with the given env."""
    full_env = {**os.environ, **env}
    return subprocess.run(
        [command, *args],
        capture_output=True,
        text=True,
        env=full_env,
    )


def test_read_timeline_returns_valid_json(bsky_live_creds):
    """Reading the home timeline should return a JSON list."""
    handle, password = bsky_live_creds
    env = {"BSKY_HANDLE": handle, "BSKY_PASSWORD": password}

    result = _run_cli("bsky-read-timeline", "--limit", "3", env=env)

    assert result.returncode == 0, f"stderr: {result.stderr}"
    data = json.loads(result.stdout)
    assert isinstance(data, list)


def test_read_notifications_returns_valid_json(bsky_live_creds):
    """Reading notifications should return a JSON list (may be empty)."""
    handle, password = bsky_live_creds
    env = {"BSKY_HANDLE": handle, "BSKY_PASSWORD": password}

    result = _run_cli("bsky-read-notifications", "--limit", "5", env=env)

    assert result.returncode == 0, f"stderr: {result.stderr}"
    data = json.loads(result.stdout)
    assert isinstance(data, list)


def test_post_and_delete_round_trip(bsky_live_creds):
    """Post a marker, find it on our timeline, then delete it.

    We can't easily get the URI from `bsky-post`'s current output (it just
    prints "posted"), so this test verifies the post happens by reading the
    author feed and finding the marker text. Then we use atproto directly
    to clean up.
    """
    handle, password = bsky_live_creds
    env = {"BSKY_HANDLE": handle, "BSKY_PASSWORD": password}

    import uuid

    marker = f"slop-studio integration test {uuid.uuid4()}"

    post_result = _run_cli("bsky-post", "--text", marker, env=env)
    assert post_result.returncode == 0, f"post stderr: {post_result.stderr}"

    feed_result = _run_cli(
        "bsky-read-timeline",
        "--actor",
        handle,
        "--limit",
        "5",
        env=env,
    )
    assert feed_result.returncode == 0
    feed = json.loads(feed_result.stdout)

    matching = [item for item in feed if marker in json.dumps(item)]
    assert matching, f"posted marker not found in own feed; marker={marker}"

    # Clean up: delete the test post via atproto directly
    from atproto import Client

    client = Client()
    client.login(handle, password)
    posts = matching[0].get("post", {})
    uri = posts.get("uri")
    if uri:
        client.delete_post(uri)
