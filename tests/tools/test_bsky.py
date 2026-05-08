"""Tests for slop_salon.tools.bsky CLI commands.

Strategy: each command is a typer app; we invoke via CliRunner and
mock atproto.Client at the import site so no real HTTP happens.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture
def bsky_env(monkeypatch):
    """Set the env vars every bsky-* command needs."""
    monkeypatch.setenv("BSKY_HANDLE", "lou.slopsalon.art")
    monkeypatch.setenv("BSKY_PASSWORD", "test-password")


@pytest.fixture
def mock_atproto_client():
    """Yield a mocked atproto.Client.

    `autospec=True` traverses the real Client signatures, so passing a
    non-existent kwarg (e.g. `reply` instead of `reply_to`) to a mocked
    method raises immediately --- catching the kind of API drift that a
    plain MagicMock silently absorbs.

    `client.app` is patched to an unrestricted MagicMock because atproto
    builds the `app.bsky.*` namespace dynamically at runtime; it isn't on
    the class, so autospec can't see it.
    """
    with patch("slop_salon.tools.bsky.Client", autospec=True) as mock_class:
        instance = mock_class.return_value
        instance.app = MagicMock()
        yield instance


def test_post_text_only(bsky_env, mock_atproto_client):
    from slop_salon.tools.bsky import post_app

    result = runner.invoke(post_app, ["--text", "hello world"])

    assert result.exit_code == 0
    mock_atproto_client.login.assert_called_once_with("lou.slopsalon.art", "test-password")
    mock_atproto_client.send_post.assert_called_once()
    args, kwargs = mock_atproto_client.send_post.call_args
    assert kwargs.get("text") == "hello world" or (args and args[0] == "hello world")


def test_post_requires_handle_env(monkeypatch, mock_atproto_client):
    monkeypatch.delenv("BSKY_HANDLE", raising=False)
    monkeypatch.setenv("BSKY_PASSWORD", "test-password")

    from slop_salon.tools.bsky import post_app

    result = runner.invoke(post_app, ["--text", "hello"])

    assert result.exit_code != 0
    assert "BSKY_HANDLE" in (result.stderr or result.output)


def test_post_requires_password_env(monkeypatch, mock_atproto_client):
    monkeypatch.setenv("BSKY_HANDLE", "lou.slopsalon.art")
    monkeypatch.delenv("BSKY_PASSWORD", raising=False)

    from slop_salon.tools.bsky import post_app

    result = runner.invoke(post_app, ["--text", "hello"])

    assert result.exit_code != 0
    assert "BSKY_PASSWORD" in (result.stderr or result.output)


def test_post_with_one_image(bsky_env, mock_atproto_client, tmp_path):
    img = tmp_path / "img.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")

    mock_atproto_client.upload_blob.return_value = MagicMock(blob="blob-ref-1")

    from slop_salon.tools.bsky import post_app

    result = runner.invoke(
        post_app,
        ["--text", "look", "--image", str(img), "--alt", "a thing"],
    )

    assert result.exit_code == 0, result.output
    mock_atproto_client.upload_blob.assert_called_once()
    mock_atproto_client.send_post.assert_called_once()


def test_post_rejects_more_than_four_images(bsky_env, mock_atproto_client, tmp_path):
    images = []
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


def test_post_image_without_alt_fails(bsky_env, mock_atproto_client, tmp_path):
    img = tmp_path / "img.jpg"
    img.write_bytes(b"x")

    from slop_salon.tools.bsky import post_app

    result = runner.invoke(post_app, ["--text", "look", "--image", str(img)])

    assert result.exit_code != 0
    assert "alt" in (result.output + (result.stderr or "")).lower()


def test_reply_to_thread(bsky_env, mock_atproto_client):
    parent_uri = "at://did:plc:xyz/app.bsky.feed.post/abc123"
    mock_atproto_client.get_posts.return_value = MagicMock(
        posts=[MagicMock(uri=parent_uri, cid="cid-abc", record=MagicMock(reply=None))]
    )

    from slop_salon.tools.bsky import reply_app

    result = runner.invoke(reply_app, ["--parent", parent_uri, "--text", "interesting"])

    assert result.exit_code == 0, result.output
    mock_atproto_client.send_post.assert_called_once()
    _, kwargs = mock_atproto_client.send_post.call_args
    assert "reply_to" in kwargs
    assert kwargs["reply_to"]["parent"]["uri"] == parent_uri


def test_quote_post(bsky_env, mock_atproto_client):
    quoted_uri = "at://did:plc:abc/app.bsky.feed.post/xyz789"
    mock_atproto_client.get_posts.return_value = MagicMock(
        posts=[MagicMock(uri=quoted_uri, cid="cid-xyz")]
    )

    from slop_salon.tools.bsky import quote_post_app

    result = runner.invoke(quote_post_app, ["--quoted", quoted_uri, "--text", "look at this"])

    assert result.exit_code == 0, result.output
    _, kwargs = mock_atproto_client.send_post.call_args
    assert kwargs["text"] == "look at this"
    assert kwargs["embed"]["$type"] == "app.bsky.embed.record"
    assert kwargs["embed"]["record"]["uri"] == quoted_uri


def test_read_timeline_default(bsky_env, mock_atproto_client):
    mock_atproto_client.get_timeline.return_value = MagicMock(
        feed=[MagicMock(model_dump=lambda **kw: {"post": {"text": "hi"}})]
    )

    from slop_salon.tools.bsky import read_timeline_app

    result = runner.invoke(read_timeline_app, ["--limit", "5"])

    assert result.exit_code == 0, result.output
    mock_atproto_client.get_timeline.assert_called_once()
    # Output should be valid JSON
    import json

    data = json.loads(result.output)
    assert isinstance(data, list)


def test_read_timeline_specific_actor(bsky_env, mock_atproto_client):
    mock_atproto_client.get_author_feed.return_value = MagicMock(
        feed=[MagicMock(model_dump=lambda **kw: {"post": {"text": "by them"}})]
    )

    from slop_salon.tools.bsky import read_timeline_app

    result = runner.invoke(read_timeline_app, ["--actor", "other.slopsalon.art", "--limit", "3"])

    assert result.exit_code == 0, result.output
    mock_atproto_client.get_author_feed.assert_called_once()


def test_read_notifications(bsky_env, mock_atproto_client):
    mock_atproto_client.app.bsky.notification.list_notifications.return_value = MagicMock(
        notifications=[MagicMock(model_dump=lambda **kw: {"reason": "reply", "uri": "at://x/y/z"})]
    )

    from slop_salon.tools.bsky import read_notifications_app

    result = runner.invoke(read_notifications_app, ["--limit", "10"])

    assert result.exit_code == 0, result.output
    import json

    data = json.loads(result.output)
    assert isinstance(data, list)
    assert data[0]["reason"] == "reply"
