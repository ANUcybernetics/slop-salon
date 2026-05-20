"""Live Bluesky integration tests.

Marked `integration` so they're skipped by default. Run with:
    uv run pytest -m integration

Use a dedicated test account; these tests post and delete real content.
"""

from __future__ import annotations

import json
import os
import subprocess
import uuid

import pytest

pytestmark = pytest.mark.integration


def _run_cli(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    """Invoke the installed `bsky` CLI with the given env."""
    full_env = {**os.environ, **env}
    return subprocess.run(
        ["bsky", *args],
        capture_output=True,
        text=True,
        env=full_env,
    )


def test_whoami_returns_did_handle_pds(bsky_live_creds):
    handle, password = bsky_live_creds
    env = {"BSKY_HANDLE": handle, "BSKY_PASSWORD": password}

    result = _run_cli("whoami", env=env)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    data = json.loads(result.stdout)
    assert data["handle"] == handle
    assert data["did"].startswith("did:")
    assert data["pds"].startswith("http")


def test_get_timeline_returns_feed_list(bsky_live_creds):
    handle, password = bsky_live_creds
    env = {"BSKY_HANDLE": handle, "BSKY_PASSWORD": password}

    result = _run_cli("get", "app.bsky.feed.getTimeline", "--param", "limit=3", env=env)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    data = json.loads(result.stdout)
    assert isinstance(data.get("feed"), list)


def test_get_notifications_returns_list(bsky_live_creds):
    handle, password = bsky_live_creds
    env = {"BSKY_HANDLE": handle, "BSKY_PASSWORD": password}

    result = _run_cli(
        "get", "app.bsky.notification.listNotifications", "--param", "limit=5", env=env
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    data = json.loads(result.stdout)
    assert isinstance(data.get("notifications"), list)


def test_post_and_delete_round_trip(bsky_live_creds):
    """Post a marker via createRecord, then delete it via deleteRecord.

    The new `bsky post com.atproto.repo.createRecord` returns the
    record's URI directly, so we can extract the rkey and delete in the
    same end-to-end flow — no SDK round-trip needed.
    """
    handle, password = bsky_live_creds
    env = {"BSKY_HANDLE": handle, "BSKY_PASSWORD": password}

    whoami = json.loads(_run_cli("whoami", env=env).stdout)
    did = whoami["did"]

    marker = f"slop-salon integration test {uuid.uuid4()}"
    from datetime import UTC, datetime

    now = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    record = {
        "repo": did,
        "collection": "app.bsky.feed.post",
        "record": {
            "$type": "app.bsky.feed.post",
            "text": marker,
            "createdAt": now,
            "langs": ["en"],
        },
    }

    post_result = _run_cli(
        "post", "com.atproto.repo.createRecord", "--json", json.dumps(record), env=env
    )
    assert post_result.returncode == 0, f"post stderr: {post_result.stderr}"
    posted = json.loads(post_result.stdout)
    uri = posted["uri"]  # at://<did>/app.bsky.feed.post/<rkey>
    rkey = uri.rsplit("/", 1)[-1]

    delete_body = {
        "repo": did,
        "collection": "app.bsky.feed.post",
        "rkey": rkey,
    }
    delete_result = _run_cli(
        "post",
        "com.atproto.repo.deleteRecord",
        "--json",
        json.dumps(delete_body),
        env=env,
    )
    assert delete_result.returncode == 0, f"delete stderr: {delete_result.stderr}"
