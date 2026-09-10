"""Tests for `slop reset` (slop_salon.reset)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slop_salon import reset as reset_mod
from slop_salon.reset import (
    BOT_SELF_LABELS,
    build_reset_profile,
    push_season_reset,
    reset,
    reset_bluesky,
)
from slop_salon.tools.bsky import Session

PDS = "https://shard.example.test"


def test_build_reset_profile_keeps_only_signup_timestamp_and_asserts_bot():
    existing = {
        "$type": "app.bsky.actor.profile",
        "avatar": {"$type": "blob", "ref": {"$link": "bafy..."}},
        "description": "the count is the fixed point",
        "displayName": "lou",
        "pinnedPost": {"uri": "at://x", "cid": "y"},
        "createdAt": "2026-05-20T01:02:03.000Z",
        # A profile that had lost its label: the reset must not need it present.
    }
    record = build_reset_profile(existing)
    assert record == {
        "$type": "app.bsky.actor.profile",
        "labels": BOT_SELF_LABELS,
        "createdAt": "2026-05-20T01:02:03.000Z",
    }


def test_build_reset_profile_does_not_fabricate_created_at():
    assert build_reset_profile(None) == {
        "$type": "app.bsky.actor.profile",
        "labels": BOT_SELF_LABELS,
    }
    assert "createdAt" not in build_reset_profile({"description": "x"})


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def seeded_remote(tmp_path: Path) -> tuple[str, str]:
    """A bare 'GitHub' repo with two commits of season-1 work. Returns (url, old head)."""
    bare = tmp_path / "remote.git"
    _git(["init", "--quiet", "--bare", "--initial-branch=main", str(bare)], cwd=tmp_path)
    work = tmp_path / "work"
    _git(["clone", "--quiet", str(bare), str(work)], cwd=tmp_path)
    _git(["config", "user.email", "t@example.test"], cwd=work)
    _git(["config", "user.name", "t"], cwd=work)
    (work / "CLAUDE.md").write_text("# lou, heavily edited\n")
    (work / "notes").mkdir()
    (work / "notes" / "2026-06-01-piece.md").write_text("made a thing\n")
    _git(["add", "-A"], cwd=work)
    _git(["commit", "--quiet", "-m", "session"], cwd=work)
    (work / "SIBLINGS.md").write_text("## mina\n\nlots of notes\n")
    _git(["add", "-A"], cwd=work)
    _git(["commit", "--quiet", "-m", "session 2"], cwd=work)
    _git(["push", "--quiet", "-u", "origin", "main"], cwd=work)
    return str(bare), _git(["rev-parse", "HEAD"], cwd=work)


def test_push_season_reset_tags_old_head_and_leaves_one_orphan_commit(
    seeded_remote, tmp_path, monkeypatch
):
    remote, old_head = seeded_remote
    monkeypatch.setenv("GIT_AUTHOR_NAME", "t")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@example.test")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "t")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@example.test")

    branch = push_season_reset(
        remote,
        {
            "CLAUDE.md": "# lou\n",
            "SIBLINGS.md": "# Siblings\n",
            "notes/.keep": "",
            "slop-tick": "#!/bin/bash\n",
        },
    )
    assert branch == "main"

    check = tmp_path / "check"
    _git(["clone", "--quiet", remote, str(check)], cwd=tmp_path)
    # The branch is one commit with exactly the reset files: no season-1 notes.
    assert _git(["rev-list", "--count", "HEAD"], cwd=check) == "1"
    assert sorted(_git(["ls-files"], cwd=check).splitlines()) == [
        "CLAUDE.md",
        "SIBLINGS.md",
        "notes/.keep",
        "slop-tick",
    ]
    assert (check / "CLAUDE.md").read_text() == "# lou\n"
    # The shebang file is committed executable, so the sprite's chmod is a no-op.
    assert _git(["ls-files", "-s", "slop-tick"], cwd=check).startswith("100755")
    # The tag preserves the old head, with its full history reachable.
    assert _git(["rev-parse", "season-1^{commit}"], cwd=check) == old_head
    assert _git(["rev-list", "--count", "season-1"], cwd=check) == "2"

    # Re-running (a retry after a failure part-way) must not move the tag onto
    # the reset commit and must still leave a single commit on the branch.
    push_season_reset(remote, {"CLAUDE.md": "# lou again\n"})
    check2 = tmp_path / "check2"
    _git(["clone", "--quiet", remote, str(check2)], cwd=tmp_path)
    assert _git(["rev-parse", "season-1^{commit}"], cwd=check2) == old_head
    assert _git(["rev-list", "--count", "HEAD"], cwd=check2) == "1"


def _session() -> Session:
    return Session(did="did:plc:lou", handle="lou.slopsalon.art", access_jwt="jwt", pds=PDS)


def _requests_to(httpx_mock, nsid: str):
    return [r for r in httpx_mock.get_requests() if nsid in str(r.url)]


def test_reset_bluesky_unfollows_every_page_and_rewrites_profile(httpx_mock):
    follow = f"{PDS}/xrpc/com.atproto.repo.listRecords"
    httpx_mock.add_response(
        url=f"{follow}?repo=did%3Aplc%3Alou&collection=app.bsky.graph.follow&limit=100",
        json={
            "records": [
                {"uri": "at://did:plc:lou/app.bsky.graph.follow/aaa", "value": {}},
                {"uri": "at://did:plc:lou/app.bsky.graph.follow/bbb", "value": {}},
            ],
            "cursor": "page2",
        },
    )
    httpx_mock.add_response(
        url=f"{follow}?repo=did%3Aplc%3Alou&collection=app.bsky.graph.follow&limit=100&cursor=page2",
        json={"records": [{"uri": "at://did:plc:lou/app.bsky.graph.follow/ccc", "value": {}}]},
    )
    httpx_mock.add_response(
        url=f"{PDS}/xrpc/com.atproto.repo.deleteRecord", json={}, is_reusable=True
    )
    httpx_mock.add_response(
        url=f"{PDS}/xrpc/com.atproto.repo.getRecord?repo=did%3Aplc%3Alou&collection=app.bsky.actor.profile&rkey=self",
        json={
            "uri": "at://did:plc:lou/app.bsky.actor.profile/self",
            "cid": "bafy",
            "value": {
                "$type": "app.bsky.actor.profile",
                "avatar": {"$type": "blob"},
                "description": "old bio",
                "createdAt": "2026-05-20T00:00:00.000Z",
            },
        },
    )
    httpx_mock.add_response(
        url=f"{PDS}/xrpc/com.atproto.repo.putRecord", json={"uri": "x", "cid": "y"}
    )

    summary = reset_bluesky(_session())

    assert summary["unfollowed"] == 3
    deletes = _requests_to(httpx_mock, "deleteRecord")
    assert [json.loads(r.content)["rkey"] for r in deletes] == ["aaa", "bbb", "ccc"]
    assert all(r.headers["authorization"] == "Bearer jwt" for r in deletes)

    (put,) = _requests_to(httpx_mock, "putRecord")
    body = json.loads(put.content)
    assert body["collection"] == "app.bsky.actor.profile"
    assert body["rkey"] == "self"
    assert body["record"] == {
        "$type": "app.bsky.actor.profile",
        "labels": BOT_SELF_LABELS,
        "createdAt": "2026-05-20T00:00:00.000Z",
    }
    assert summary["profile"] == body["record"]


def test_reset_bluesky_writes_profile_even_when_none_exists(httpx_mock):
    httpx_mock.add_response(
        url=f"{PDS}/xrpc/com.atproto.repo.listRecords?repo=did%3Aplc%3Alou&collection=app.bsky.graph.follow&limit=100",
        json={"records": []},
    )
    httpx_mock.add_response(
        url=f"{PDS}/xrpc/com.atproto.repo.getRecord?repo=did%3Aplc%3Alou&collection=app.bsky.actor.profile&rkey=self",
        status_code=400,
        json={"error": "RecordNotFound", "message": "Could not locate record"},
    )
    httpx_mock.add_response(url=f"{PDS}/xrpc/com.atproto.repo.putRecord", json={})

    summary = reset_bluesky(_session())

    assert summary["unfollowed"] == 0
    assert summary["profile"] == {"$type": "app.bsky.actor.profile", "labels": BOT_SELF_LABELS}


@pytest.fixture
def reset_config(tmp_path, monkeypatch):
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "CLAUDE.md").write_text("# {{name}} ({{handle}})")
    (tmp_path / "templates" / "SIBLINGS.md").write_text("# Siblings\n\n{{siblings_section}}")
    (tmp_path / "SOUL.md").write_text("# Soul")
    cfg = tmp_path / "slop_salon.toml"
    cfg.write_text(
        """
[providers.season2]
runner = "claude"
env = { AGENT_MODEL = "x" }
secret_env = { OPENROUTER_API_KEY = "TEST_OPENROUTER_KEY" }

[salons.one]
provider = "season2"

[agents.lou]
handle = "lou.slopsalon.art"
github_repo = "ANUcybernetics/slop-salon-lou"
sprite_id = "lou"
salon = "one"
live = true

[agents.mina]
handle = "mina.slopsalon.art"
github_repo = "ANUcybernetics/slop-salon-mina"
sprite_id = "mina"
salon = "one"
live = true
"""
    )
    monkeypatch.setenv("TEST_OPENROUTER_KEY", "not-a-key")
    monkeypatch.chdir(tmp_path)
    return cfg


def test_reset_runs_steps_in_order_with_fresh_siblings(reset_config):
    order: list[str] = []
    session = _session()

    with (
        patch.object(
            reset_mod,
            "resolve_secrets",
            return_value={"GH_TOKEN": "ghp_x", "BSKY_PASSWORD": "pw"},
        ),
        patch.object(reset_mod, "SpritesClient") as sprites_class,
        patch.object(
            reset_mod, "create_session", side_effect=lambda *a: order.append("session") or session
        ) as create,
        patch.object(
            reset_mod, "_preflight_sprite", side_effect=lambda *a: order.append("preflight")
        ) as preflight,
        patch.object(
            reset_mod,
            "push_season_reset",
            side_effect=lambda *a, **k: order.append("push") or "main",
        ) as push,
        patch.object(
            reset_mod, "recreate", side_effect=lambda *a, **k: order.append("recreate")
        ) as recreate,
        patch.object(
            reset_mod,
            "reset_bluesky",
            side_effect=lambda *a: order.append("bluesky") or {"unfollowed": 5, "profile": {}},
        ) as bluesky,
    ):
        sprites = MagicMock()
        sprites_class.return_value = sprites
        reset("lou")

    # Auth and pre-flight come before anything destructive; the sprite is
    # rebuilt only after the branch it clones has been replaced; the timeline
    # is cleaned last.
    assert order == ["session", "preflight", "push", "recreate", "bluesky"]
    create.assert_called_once_with("lou.slopsalon.art", "pw")
    preflight.assert_called_once_with(sprites, "lou", "~/slop-salon-lou")
    recreate.assert_called_once_with("lou", config_path="slop_salon.toml", sprites=sprites)
    bluesky.assert_called_once_with(session)

    remote, files = push.call_args.args
    assert remote == "https://ghp_x@github.com/ANUcybernetics/slop-salon-lou.git"
    assert push.call_args.kwargs == {"tag": "season-1"}
    # Freshly interpolated templates: a stub sibling entry, not carried notes.
    assert files["CLAUDE.md"] == "# lou (lou.slopsalon.art)"
    assert "## mina" in files["SIBLINGS.md"]
    assert "No observations yet" in files["SIBLINGS.md"]
    assert files["SOUL.md"] == "# Soul"


def test_reset_fails_before_any_write_when_bluesky_login_fails(reset_config):
    with (
        patch.object(
            reset_mod,
            "resolve_secrets",
            return_value={"GH_TOKEN": "ghp_x", "BSKY_PASSWORD": "wrong"},
        ),
        patch.object(reset_mod, "SpritesClient"),
        patch.object(reset_mod, "create_session", side_effect=SystemExit(1)),
        patch.object(reset_mod, "push_season_reset") as push,
        patch.object(reset_mod, "recreate") as recreate,
        pytest.raises(SystemExit),
    ):
        reset("lou")
    push.assert_not_called()
    recreate.assert_not_called()


def test_reset_skips_are_honoured(reset_config):
    with (
        patch.object(reset_mod, "resolve_secrets", return_value={"GH_TOKEN": "ghp_x"}),
        patch.object(reset_mod, "SpritesClient"),
        patch.object(reset_mod, "create_session") as create,
        patch.object(reset_mod, "_preflight_sprite") as preflight,
        patch.object(reset_mod, "push_season_reset", return_value="main") as push,
        patch.object(reset_mod, "recreate") as recreate,
        patch.object(reset_mod, "reset_bluesky") as bluesky,
    ):
        reset("lou", skip_sprite=True, skip_bluesky=True, tag="season-3")
    create.assert_not_called()
    preflight.assert_not_called()
    recreate.assert_not_called()
    bluesky.assert_not_called()
    assert push.call_args.kwargs == {"tag": "season-3"}


def test_reset_retry_after_bluesky_failure_touches_only_bluesky(reset_config):
    """The retry the docstring promises: --skip-repo --skip-sprite redoes step 5 alone."""
    session = _session()
    with (
        patch.object(
            reset_mod, "resolve_secrets", return_value={"GH_TOKEN": "ghp_x", "BSKY_PASSWORD": "pw"}
        ),
        patch.object(reset_mod, "SpritesClient"),
        patch.object(reset_mod, "create_session", return_value=session),
        patch.object(reset_mod, "_preflight_sprite") as preflight,
        patch.object(reset_mod, "push_season_reset") as push,
        patch.object(reset_mod, "recreate") as recreate,
        patch.object(
            reset_mod, "reset_bluesky", return_value={"unfollowed": 6, "profile": {}}
        ) as bluesky,
    ):
        reset("lou", skip_repo=True, skip_sprite=True)
    preflight.assert_not_called()
    push.assert_not_called()
    recreate.assert_not_called()
    bluesky.assert_called_once_with(session)
