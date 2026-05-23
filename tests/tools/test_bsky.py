"""Tests for the single-tool `bsky` CLI.

Strategy: mock HTTP at the wire level via pytest-httpx and assert on the
exact requests Bluesky receives — URLs, methods, headers, JSON bodies.
This catches mistakes in URL construction, content-type detection, and
auth wiring that a higher-level mock would silently absorb.

The tool is intentionally thin: it doesn't know about feed.post / follow /
reply record shapes. So the tests here only cover the wrapper primitives
(GET with params, POST with --json, POST with --file, whoami, auth). The
correctness of multi-call recipes (reply threading, unfollow's rkey
lookup, etc.) lives in the agent's prompt and the help-text cookbook —
not in this code.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

runner = CliRunner()

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
    matches = [r for r in httpx_mock.get_requests() if path_substring in str(r.url)]
    if not matches:
        raise AssertionError(
            f"No request found matching {path_substring!r}. "
            f"Got: {[str(r.url) for r in httpx_mock.get_requests()]}"
        )
    if len(matches) > 1:
        raise AssertionError(f"Multiple requests match {path_substring!r}: {len(matches)}")
    return matches[0]


# === Auth + env validation =================================================


def test_get_requires_handle_env(monkeypatch):
    monkeypatch.delenv("BSKY_HANDLE", raising=False)
    monkeypatch.setenv("BSKY_PASSWORD", "test-password")
    from slop_salon.tools.bsky import app

    result = runner.invoke(app, ["get", "app.bsky.feed.getTimeline"])
    assert result.exit_code != 0
    assert "BSKY_HANDLE" in (result.stderr or result.output)


def test_post_requires_password_env(monkeypatch):
    monkeypatch.setenv("BSKY_HANDLE", FAKE_HANDLE)
    monkeypatch.delenv("BSKY_PASSWORD", raising=False)
    from slop_salon.tools.bsky import app

    result = runner.invoke(app, ["post", "com.atproto.repo.createRecord", "--json", "{}"])
    assert result.exit_code != 0
    assert "BSKY_PASSWORD" in (result.stderr or result.output)


def test_calls_use_pds_from_did_doc_with_bearer_auth(bsky_env, session_mock, httpx_mock):
    """After createSession on bsky.social, every call should hit FAKE_PDS with the JWT."""
    httpx_mock.add_response(
        method="GET",
        url=f"{FAKE_PDS}/xrpc/app.bsky.feed.getTimeline",
        json={"feed": []},
    )
    from slop_salon.tools.bsky import app

    result = runner.invoke(app, ["get", "app.bsky.feed.getTimeline"])
    assert result.exit_code == 0, result.output

    req = _find_request(httpx_mock, "getTimeline")
    assert str(req.url).startswith(FAKE_PDS)
    assert req.headers["authorization"] == f"Bearer {FAKE_JWT}"


def test_create_session_failure_exits_nonzero(bsky_env, httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://bsky.social/xrpc/com.atproto.server.createSession",
        status_code=401,
        json={"error": "AuthenticationRequired", "message": "Invalid identifier or password"},
    )
    from slop_salon.tools.bsky import app

    result = runner.invoke(app, ["get", "app.bsky.feed.getTimeline"])
    assert result.exit_code != 0
    assert "AuthenticationRequired" in (result.output + (result.stderr or ""))


# === whoami ================================================================


def test_whoami_prints_did_handle_pds_json(bsky_env, session_mock):
    from slop_salon.tools.bsky import app

    result = runner.invoke(app, ["whoami"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data == {"did": FAKE_DID, "handle": FAKE_HANDLE, "pds": FAKE_PDS}


def test_cookbook_prints_recipes_with_whitespace_preserved():
    """The cookbook prints raw text (not via typer's help renderer), so the
    shell recipe whitespace must survive intact for jq to parse them."""
    from slop_salon.tools.bsky import app

    result = runner.invoke(app, ["cookbook"])
    assert result.exit_code == 0, result.output
    # Spot-check that recipes are present and that the threading caveat
    # survives (this is the part most likely to silently mislead an agent).
    assert "bsky whoami" in result.output
    assert "com.atproto.repo.createRecord" in result.output
    assert "THREAD ROOT" in result.output
    assert "app.bsky.actor.profile" in result.output
    # The audio-as-video recipe is the only path to share audio on Bluesky.
    assert "app.bsky.embed.video" in result.output
    assert "ffmpeg" in result.output


# === get ===================================================================


def test_get_with_no_params(bsky_env, session_mock, httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url=f"{FAKE_PDS}/xrpc/app.bsky.notification.listNotifications",
        json={"notifications": [{"reason": "reply"}]},
    )
    from slop_salon.tools.bsky import app

    result = runner.invoke(app, ["get", "app.bsky.notification.listNotifications"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"notifications": [{"reason": "reply"}]}


def test_get_with_single_param(bsky_env, session_mock, httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url=f"{FAKE_PDS}/xrpc/app.bsky.feed.getTimeline?limit=5",
        json={"feed": []},
    )
    from slop_salon.tools.bsky import app

    result = runner.invoke(app, ["get", "app.bsky.feed.getTimeline", "--param", "limit=5"])
    assert result.exit_code == 0, result.output


def test_get_with_multiple_params_same_key_makes_array(bsky_env, session_mock, httpx_mock):
    """ATProto arrays in URL params are repeated keys: ?uris=a&uris=b."""
    uri_a = "at://did:plc:x/app.bsky.feed.post/a"
    uri_b = "at://did:plc:y/app.bsky.feed.post/b"
    httpx_mock.add_response(
        method="GET",
        url=f"{FAKE_PDS}/xrpc/app.bsky.feed.getPosts?uris={uri_a}&uris={uri_b}",
        json={"posts": []},
    )
    from slop_salon.tools.bsky import app

    result = runner.invoke(
        app,
        ["get", "app.bsky.feed.getPosts", "--param", f"uris={uri_a}", "--param", f"uris={uri_b}"],
    )
    assert result.exit_code == 0, result.output


def test_get_rejects_param_without_equals(bsky_env):
    """Param validation runs before auth, so no HTTP traffic should happen."""
    from slop_salon.tools.bsky import app

    result = runner.invoke(app, ["get", "app.bsky.feed.getTimeline", "--param", "limit"])
    assert result.exit_code != 0
    assert "key=value" in (result.output + (result.stderr or ""))


def test_get_surfaces_xrpc_error(bsky_env, session_mock, httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url=f"{FAKE_PDS}/xrpc/app.bsky.feed.getPosts",
        status_code=400,
        json={"error": "InvalidRequest", "message": "missing uris"},
    )
    from slop_salon.tools.bsky import app

    result = runner.invoke(app, ["get", "app.bsky.feed.getPosts"])
    assert result.exit_code != 0
    assert "InvalidRequest" in (result.output + (result.stderr or ""))
    assert "missing uris" in (result.output + (result.stderr or ""))


# === post ==================================================================


def test_post_with_json_body(bsky_env, session_mock, httpx_mock):
    body = {
        "repo": FAKE_DID,
        "collection": "app.bsky.feed.post",
        "record": {
            "$type": "app.bsky.feed.post",
            "text": "hello",
            "createdAt": "2026-05-20T12:00:00.000Z",
            "langs": ["en"],
        },
    }
    httpx_mock.add_response(
        method="POST",
        url=f"{FAKE_PDS}/xrpc/com.atproto.repo.createRecord",
        json={"uri": "at://did:plc:fake123/app.bsky.feed.post/abc", "cid": "cid-abc"},
    )
    from slop_salon.tools.bsky import app

    result = runner.invoke(
        app, ["post", "com.atproto.repo.createRecord", "--json", json.dumps(body)]
    )
    assert result.exit_code == 0, result.output
    assert "at://did:plc:fake123" in result.output

    req = _find_request(httpx_mock, "createRecord")
    assert req.headers.get("content-type", "").startswith("application/json")
    assert json.loads(req.content) == body


def test_post_with_file_uses_detected_mime_and_raw_bytes(
    bsky_env, session_mock, httpx_mock, tmp_path
):
    img = tmp_path / "img.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")
    httpx_mock.add_response(
        method="POST",
        url=f"{FAKE_PDS}/xrpc/com.atproto.repo.uploadBlob",
        json={
            "blob": {
                "$type": "blob",
                "ref": {"$link": "bafy-fake"},
                "mimeType": "image/jpeg",
                "size": 14,
            }
        },
    )
    from slop_salon.tools.bsky import app

    result = runner.invoke(app, ["post", "com.atproto.repo.uploadBlob", "--file", str(img)])
    assert result.exit_code == 0, result.output

    req = _find_request(httpx_mock, "uploadBlob")
    assert req.headers["content-type"] == "image/jpeg"
    assert req.content == b"\xff\xd8\xff\xe0fake-jpeg"
    assert "bafy-fake" in result.output


def test_post_file_unknown_extension_falls_back_to_octet_stream(
    bsky_env, session_mock, httpx_mock, tmp_path
):
    blob = tmp_path / "weird.xyzzy"
    blob.write_bytes(b"opaque")
    httpx_mock.add_response(
        method="POST",
        url=f"{FAKE_PDS}/xrpc/com.atproto.repo.uploadBlob",
        json={"blob": {}},
    )
    from slop_salon.tools.bsky import app

    result = runner.invoke(app, ["post", "com.atproto.repo.uploadBlob", "--file", str(blob)])
    assert result.exit_code == 0, result.output
    req = _find_request(httpx_mock, "uploadBlob")
    assert req.headers["content-type"] == "application/octet-stream"


def test_post_rejects_json_and_file_together(bsky_env, tmp_path):
    """Mutex check runs before auth, so no HTTP traffic should happen."""
    img = tmp_path / "img.jpg"
    img.write_bytes(b"x")
    from slop_salon.tools.bsky import app

    result = runner.invoke(
        app,
        [
            "post",
            "com.atproto.repo.uploadBlob",
            "--json",
            "{}",
            "--file",
            str(img),
        ],
    )
    assert result.exit_code != 0
    assert "mutually exclusive" in (result.output + (result.stderr or ""))


def test_post_rejects_invalid_json(bsky_env):
    """JSON validation runs before auth, so no HTTP traffic should happen."""
    from slop_salon.tools.bsky import app

    result = runner.invoke(app, ["post", "com.atproto.repo.createRecord", "--json", "{not json"])
    assert result.exit_code != 0
    assert "valid JSON" in (result.output + (result.stderr or ""))


def test_post_surfaces_xrpc_error(bsky_env, session_mock, httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url=f"{FAKE_PDS}/xrpc/com.atproto.repo.createRecord",
        status_code=400,
        json={"error": "InvalidRequest", "message": "Record is invalid"},
    )
    from slop_salon.tools.bsky import app

    result = runner.invoke(app, ["post", "com.atproto.repo.createRecord", "--json", "{}"])
    assert result.exit_code != 0
    assert "InvalidRequest" in (result.output + (result.stderr or ""))
    assert "Record is invalid" in (result.output + (result.stderr or ""))
