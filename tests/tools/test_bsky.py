"""Tests for slop_salon.tools.bsky CLI commands.

Strategy: mock HTTP at the wire level via pytest-httpx and assert on the
exact requests Bluesky receives — URLs, methods, headers, JSON bodies.
This catches mistakes in record construction (wrong $type, wrong field
name, missing createdAt, etc.) that mocking the SDK would silently
absorb.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

runner = CliRunner()

# Wire-level fixtures: the test bsky.social returns these, and every PDS-
# bound call should go to FAKE_PDS afterwards.
FAKE_PDS = "https://pds.test.example.com"
FAKE_DID = "did:plc:fake123"
FAKE_HANDLE = "lou.slopsalon.art"
FAKE_JWT = "fake-jwt-abc"


@pytest.fixture
def bsky_env(monkeypatch):
    monkeypatch.setenv("BSKY_HANDLE", FAKE_HANDLE)
    monkeypatch.setenv("BSKY_PASSWORD", "test-password")


@pytest.fixture
def session_mock(httpx_mock):
    """Mock createSession so _get_session returns a known Session pointed at FAKE_PDS."""
    httpx_mock.add_response(
        method="POST",
        url="https://bsky.social/xrpc/com.atproto.server.createSession",
        json={
            "did": FAKE_DID,
            "handle": FAKE_HANDLE,
            "accessJwt": FAKE_JWT,
            "refreshJwt": "fake-refresh",
            "didDoc": {
                "service": [
                    {
                        "id": "#atproto_pds",
                        "type": "AtprotoPersonalDataServer",
                        "serviceEndpoint": FAKE_PDS,
                    }
                ],
            },
        },
    )


def _find_request(httpx_mock, path_substring: str):
    """Return the (single) request whose URL contains the given substring."""
    matches = [r for r in httpx_mock.get_requests() if path_substring in str(r.url)]
    if not matches:
        raise AssertionError(
            f"No request found matching {path_substring!r}. "
            f"Got: {[str(r.url) for r in httpx_mock.get_requests()]}"
        )
    if len(matches) > 1:
        raise AssertionError(f"Multiple requests match {path_substring!r}: {len(matches)}")
    return matches[0]


def _json_body(req) -> dict:
    return json.loads(req.content)


def _assert_post_record_basics(record: dict, expected_text: str) -> None:
    """Every app.bsky.feed.post must have these baseline fields."""
    assert record["$type"] == "app.bsky.feed.post"
    assert record["text"] == expected_text
    assert "createdAt" in record
    # ISO 8601 with ms precision and Z suffix.
    assert record["createdAt"].endswith("Z")
    assert "." in record["createdAt"]
    assert record["langs"] == ["en"]


# === Auth + env validation =================================================


def test_post_requires_handle_env(monkeypatch):
    monkeypatch.delenv("BSKY_HANDLE", raising=False)
    monkeypatch.setenv("BSKY_PASSWORD", "test-password")
    from slop_salon.tools.bsky import post_app

    result = runner.invoke(post_app, ["--text", "hello"])
    assert result.exit_code != 0
    assert "BSKY_HANDLE" in (result.stderr or result.output)


def test_post_requires_password_env(monkeypatch):
    monkeypatch.setenv("BSKY_HANDLE", FAKE_HANDLE)
    monkeypatch.delenv("BSKY_PASSWORD", raising=False)
    from slop_salon.tools.bsky import post_app

    result = runner.invoke(post_app, ["--text", "hello"])
    assert result.exit_code != 0
    assert "BSKY_PASSWORD" in (result.stderr or result.output)


def test_session_uses_pds_from_did_doc(bsky_env, session_mock, httpx_mock):
    """createRecord must hit the PDS from didDoc, not bsky.social."""
    httpx_mock.add_response(
        method="POST",
        url=f"{FAKE_PDS}/xrpc/com.atproto.repo.createRecord",
        json={"uri": "at://x/y/z", "cid": "c"},
    )
    from slop_salon.tools.bsky import post_app

    result = runner.invoke(post_app, ["--text", "hi"])
    assert result.exit_code == 0, result.output

    create_req = _find_request(httpx_mock, "createRecord")
    assert str(create_req.url).startswith(FAKE_PDS)
    assert create_req.headers["authorization"] == f"Bearer {FAKE_JWT}"


# === Post =================================================================


def test_post_text_only(bsky_env, session_mock, httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url=f"{FAKE_PDS}/xrpc/com.atproto.repo.createRecord",
        json={"uri": "at://did:plc:fake123/app.bsky.feed.post/abc", "cid": "cid-abc"},
    )
    from slop_salon.tools.bsky import post_app

    result = runner.invoke(post_app, ["--text", "hello world"])
    assert result.exit_code == 0, result.output
    assert "at://did:plc:fake123" in result.output

    body = _json_body(_find_request(httpx_mock, "createRecord"))
    assert body["repo"] == FAKE_DID
    assert body["collection"] == "app.bsky.feed.post"
    _assert_post_record_basics(body["record"], "hello world")
    assert "embed" not in body["record"]
    assert "reply" not in body["record"]


def test_post_with_one_image(bsky_env, session_mock, httpx_mock, tmp_path):
    img = tmp_path / "img.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")
    fake_blob = {
        "$type": "blob",
        "ref": {"$link": "bafy-fake"},
        "mimeType": "image/jpeg",
        "size": 14,
    }
    httpx_mock.add_response(
        method="POST",
        url=f"{FAKE_PDS}/xrpc/com.atproto.repo.uploadBlob",
        json={"blob": fake_blob},
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{FAKE_PDS}/xrpc/com.atproto.repo.createRecord",
        json={"uri": "at://x/y/z", "cid": "c"},
    )
    from slop_salon.tools.bsky import post_app

    result = runner.invoke(
        post_app, ["--text", "look", "--image", str(img), "--alt", "a thing"]
    )
    assert result.exit_code == 0, result.output

    upload_req = _find_request(httpx_mock, "uploadBlob")
    assert upload_req.headers["content-type"] == "image/jpeg"
    assert upload_req.content == b"\xff\xd8\xff\xe0fake-jpeg"

    body = _json_body(_find_request(httpx_mock, "createRecord"))
    embed = body["record"]["embed"]
    assert embed["$type"] == "app.bsky.embed.images"
    assert len(embed["images"]) == 1
    assert embed["images"][0]["alt"] == "a thing"
    assert embed["images"][0]["image"] == fake_blob


def test_post_with_video(bsky_env, session_mock, httpx_mock, tmp_path):
    vid = tmp_path / "clip.mp4"
    vid.write_bytes(b"\x00\x00fake-mp4")
    fake_blob = {"$type": "blob", "ref": {"$link": "bafy-vid"}, "mimeType": "video/mp4"}
    httpx_mock.add_response(
        method="POST",
        url=f"{FAKE_PDS}/xrpc/com.atproto.repo.uploadBlob",
        json={"blob": fake_blob},
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{FAKE_PDS}/xrpc/com.atproto.repo.createRecord",
        json={"uri": "at://x/y/z", "cid": "c"},
    )
    from slop_salon.tools.bsky import post_app

    result = runner.invoke(post_app, ["--text", "rolling", "--video", str(vid)])
    assert result.exit_code == 0, result.output

    upload_req = _find_request(httpx_mock, "uploadBlob")
    assert upload_req.headers["content-type"] == "video/mp4"

    body = _json_body(_find_request(httpx_mock, "createRecord"))
    embed = body["record"]["embed"]
    assert embed["$type"] == "app.bsky.embed.video"
    assert embed["video"] == fake_blob


def test_post_rejects_more_than_four_images(bsky_env, tmp_path):
    """Client-side validation: no HTTP traffic should happen."""
    images: list[Path] = []
    for i in range(5):
        p = tmp_path / f"img{i}.jpg"
        p.write_bytes(b"x")
        images.append(p)
    from slop_salon.tools.bsky import post_app

    args = ["--text", "many"]
    for p in images:
        args += ["--image", str(p), "--alt", "x"]
    result = runner.invoke(post_app, args)
    assert result.exit_code != 0
    assert "4" in (result.output + (result.stderr or ""))


def test_post_image_without_alt_fails(bsky_env, tmp_path):
    img = tmp_path / "img.jpg"
    img.write_bytes(b"x")
    from slop_salon.tools.bsky import post_app

    result = runner.invoke(post_app, ["--text", "look", "--image", str(img)])
    assert result.exit_code != 0
    assert "alt" in (result.output + (result.stderr or "")).lower()


# === Reply ================================================================


def test_reply_to_top_level_post(bsky_env, session_mock, httpx_mock):
    parent_uri = "at://did:plc:xyz/app.bsky.feed.post/parent1"
    httpx_mock.add_response(
        method="GET",
        url=f"{FAKE_PDS}/xrpc/app.bsky.feed.getPosts?uris={parent_uri}",
        json={
            "posts": [
                {
                    "uri": parent_uri,
                    "cid": "cid-parent",
                    "record": {"$type": "app.bsky.feed.post", "text": "thinking out loud"},
                }
            ]
        },
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{FAKE_PDS}/xrpc/com.atproto.repo.createRecord",
        json={"uri": "at://x/y/z", "cid": "c"},
    )
    from slop_salon.tools.bsky import reply_app

    result = runner.invoke(reply_app, ["--parent", parent_uri, "--text", "interesting"])
    assert result.exit_code == 0, result.output

    body = _json_body(_find_request(httpx_mock, "createRecord"))
    _assert_post_record_basics(body["record"], "interesting")
    # For a top-level reply, root and parent are the same.
    expected_ref = {"uri": parent_uri, "cid": "cid-parent"}
    assert body["record"]["reply"] == {"parent": expected_ref, "root": expected_ref}


def test_reply_to_nested_reply_threads_back_to_root(bsky_env, session_mock, httpx_mock):
    parent_uri = "at://did:plc:xyz/app.bsky.feed.post/middle"
    root_ref = {"uri": "at://did:plc:xyz/app.bsky.feed.post/root", "cid": "cid-root"}
    httpx_mock.add_response(
        method="GET",
        url=f"{FAKE_PDS}/xrpc/app.bsky.feed.getPosts?uris={parent_uri}",
        json={
            "posts": [
                {
                    "uri": parent_uri,
                    "cid": "cid-middle",
                    "record": {
                        "$type": "app.bsky.feed.post",
                        "text": "mid-thread",
                        "reply": {"root": root_ref, "parent": {"uri": "...", "cid": "..."}},
                    },
                }
            ]
        },
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{FAKE_PDS}/xrpc/com.atproto.repo.createRecord",
        json={"uri": "at://x/y/z", "cid": "c"},
    )
    from slop_salon.tools.bsky import reply_app

    result = runner.invoke(reply_app, ["--parent", parent_uri, "--text", "agree"])
    assert result.exit_code == 0, result.output

    body = _json_body(_find_request(httpx_mock, "createRecord"))
    assert body["record"]["reply"]["root"] == root_ref
    assert body["record"]["reply"]["parent"] == {"uri": parent_uri, "cid": "cid-middle"}


# === Quote post ===========================================================


def test_quote_post_text_only(bsky_env, session_mock, httpx_mock):
    quoted_uri = "at://did:plc:abc/app.bsky.feed.post/xyz789"
    httpx_mock.add_response(
        method="GET",
        url=f"{FAKE_PDS}/xrpc/app.bsky.feed.getPosts?uris={quoted_uri}",
        json={"posts": [{"uri": quoted_uri, "cid": "cid-xyz"}]},
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{FAKE_PDS}/xrpc/com.atproto.repo.createRecord",
        json={"uri": "at://x/y/z", "cid": "c"},
    )
    from slop_salon.tools.bsky import quote_post_app

    result = runner.invoke(
        quote_post_app, ["--quoted", quoted_uri, "--text", "look at this"]
    )
    assert result.exit_code == 0, result.output

    body = _json_body(_find_request(httpx_mock, "createRecord"))
    _assert_post_record_basics(body["record"], "look at this")
    embed = body["record"]["embed"]
    assert embed["$type"] == "app.bsky.embed.record"
    assert embed["record"] == {"uri": quoted_uri, "cid": "cid-xyz"}


def test_quote_post_with_image_uses_record_with_media(bsky_env, session_mock, httpx_mock, tmp_path):
    quoted_uri = "at://did:plc:abc/app.bsky.feed.post/xyz"
    img = tmp_path / "img.png"
    img.write_bytes(b"\x89PNGfake")
    httpx_mock.add_response(
        method="GET",
        url=f"{FAKE_PDS}/xrpc/app.bsky.feed.getPosts?uris={quoted_uri}",
        json={"posts": [{"uri": quoted_uri, "cid": "cid-q"}]},
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{FAKE_PDS}/xrpc/com.atproto.repo.uploadBlob",
        json={"blob": {"$type": "blob", "ref": {"$link": "bafy"}, "mimeType": "image/png"}},
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{FAKE_PDS}/xrpc/com.atproto.repo.createRecord",
        json={"uri": "at://x/y/z", "cid": "c"},
    )
    from slop_salon.tools.bsky import quote_post_app

    result = runner.invoke(
        quote_post_app,
        ["--quoted", quoted_uri, "--text", "see also", "--image", str(img), "--alt", "thing"],
    )
    assert result.exit_code == 0, result.output

    body = _json_body(_find_request(httpx_mock, "createRecord"))
    embed = body["record"]["embed"]
    assert embed["$type"] == "app.bsky.embed.recordWithMedia"
    assert embed["record"]["record"]["uri"] == quoted_uri
    assert embed["media"]["$type"] == "app.bsky.embed.images"


# === Follow ===============================================================


def test_follow_resolves_handle_then_creates_record(bsky_env, session_mock, httpx_mock):
    target_did = "did:plc:mina-fake"
    httpx_mock.add_response(
        method="GET",
        url=f"{FAKE_PDS}/xrpc/com.atproto.identity.resolveHandle?handle=mina.slopsalon.art",
        json={"did": target_did},
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{FAKE_PDS}/xrpc/com.atproto.repo.createRecord",
        json={"uri": f"at://{FAKE_DID}/app.bsky.graph.follow/abc", "cid": "c"},
    )
    from slop_salon.tools.bsky import follow_app

    result = runner.invoke(follow_app, ["--handle", "mina.slopsalon.art"])
    assert result.exit_code == 0, result.output

    body = _json_body(_find_request(httpx_mock, "createRecord"))
    assert body["repo"] == FAKE_DID
    assert body["collection"] == "app.bsky.graph.follow"
    assert body["record"]["$type"] == "app.bsky.graph.follow"
    assert body["record"]["subject"] == target_did
    assert "createdAt" in body["record"]


# === Unfollow =============================================================


def test_unfollow_resolves_handle_lists_records_and_deletes(
    bsky_env, session_mock, httpx_mock
):
    target_did = "did:plc:target"
    target_rkey = "rkey-target"
    other_rkey = "rkey-other"
    httpx_mock.add_response(
        method="GET",
        url=f"{FAKE_PDS}/xrpc/com.atproto.identity.resolveHandle?handle=bsky.app",
        json={"did": target_did},
    )
    # listRecords returns two follows; we should pick the one matching subject.
    httpx_mock.add_response(
        method="GET",
        url=(
            f"{FAKE_PDS}/xrpc/com.atproto.repo.listRecords"
            f"?repo={FAKE_DID}&collection=app.bsky.graph.follow&limit=100"
        ),
        json={
            "records": [
                {
                    "uri": f"at://{FAKE_DID}/app.bsky.graph.follow/{other_rkey}",
                    "value": {"subject": "did:plc:someone-else"},
                },
                {
                    "uri": f"at://{FAKE_DID}/app.bsky.graph.follow/{target_rkey}",
                    "value": {"subject": target_did},
                },
            ],
        },
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{FAKE_PDS}/xrpc/com.atproto.repo.deleteRecord",
        json={},
    )
    from slop_salon.tools.bsky import unfollow_app

    result = runner.invoke(unfollow_app, ["--handle", "bsky.app"])
    assert result.exit_code == 0, result.output

    body = _json_body(_find_request(httpx_mock, "deleteRecord"))
    assert body == {
        "repo": FAKE_DID,
        "collection": "app.bsky.graph.follow",
        "rkey": target_rkey,
    }


def test_unfollow_is_idempotent_when_not_following(bsky_env, session_mock, httpx_mock):
    target_did = "did:plc:stranger"
    httpx_mock.add_response(
        method="GET",
        url=f"{FAKE_PDS}/xrpc/com.atproto.identity.resolveHandle?handle=stranger.bsky.social",
        json={"did": target_did},
    )
    httpx_mock.add_response(
        method="GET",
        url=(
            f"{FAKE_PDS}/xrpc/com.atproto.repo.listRecords"
            f"?repo={FAKE_DID}&collection=app.bsky.graph.follow&limit=100"
        ),
        json={"records": []},
    )
    from slop_salon.tools.bsky import unfollow_app

    result = runner.invoke(unfollow_app, ["--handle", "stranger.bsky.social"])
    assert result.exit_code == 0, result.output
    assert "not following" in result.output

    # Crucially, no deleteRecord call should have been made.
    delete_calls = [
        r for r in httpx_mock.get_requests() if "deleteRecord" in str(r.url)
    ]
    assert delete_calls == []


# === Reads ================================================================


def test_read_timeline_default(bsky_env, session_mock, httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url=f"{FAKE_PDS}/xrpc/app.bsky.feed.getTimeline?limit=5",
        json={"feed": [{"post": {"text": "hi"}}]},
    )
    from slop_salon.tools.bsky import read_timeline_app

    result = runner.invoke(read_timeline_app, ["--limit", "5"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data == [{"post": {"text": "hi"}}]

    req = _find_request(httpx_mock, "getTimeline")
    assert req.headers["authorization"] == f"Bearer {FAKE_JWT}"


def test_read_timeline_specific_actor(bsky_env, session_mock, httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url=f"{FAKE_PDS}/xrpc/app.bsky.feed.getAuthorFeed?actor=other.slopsalon.art&limit=3",
        json={"feed": [{"post": {"text": "by them"}}]},
    )
    from slop_salon.tools.bsky import read_timeline_app

    result = runner.invoke(
        read_timeline_app, ["--actor", "other.slopsalon.art", "--limit", "3"]
    )
    assert result.exit_code == 0, result.output
    _find_request(httpx_mock, "getAuthorFeed")


def test_read_notifications(bsky_env, session_mock, httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url=f"{FAKE_PDS}/xrpc/app.bsky.notification.listNotifications?limit=10",
        json={"notifications": [{"reason": "reply", "uri": "at://x/y/z"}]},
    )
    from slop_salon.tools.bsky import read_notifications_app

    result = runner.invoke(read_notifications_app, ["--limit", "10"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data == [{"reason": "reply", "uri": "at://x/y/z"}]


# === Error handling =======================================================


def test_create_session_failure_exits_nonzero(bsky_env, httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://bsky.social/xrpc/com.atproto.server.createSession",
        status_code=401,
        json={"error": "AuthenticationRequired", "message": "Invalid identifier or password"},
    )
    from slop_salon.tools.bsky import post_app

    result = runner.invoke(post_app, ["--text", "hi"])
    assert result.exit_code != 0
    assert "AuthenticationRequired" in (result.output + (result.stderr or ""))


def test_create_record_failure_surfaces_error_message(bsky_env, session_mock, httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url=f"{FAKE_PDS}/xrpc/com.atproto.repo.createRecord",
        status_code=400,
        json={"error": "InvalidRequest", "message": "Record is invalid"},
    )
    from slop_salon.tools.bsky import post_app

    result = runner.invoke(post_app, ["--text", "hi"])
    assert result.exit_code != 0
    assert "InvalidRequest" in (result.output + (result.stderr or ""))
    assert "Record is invalid" in (result.output + (result.stderr or ""))
