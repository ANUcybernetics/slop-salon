"""Tests for `slop-studio`, the per-tick studio-state cue."""

from __future__ import annotations

from slop_salon.tools import studio
from slop_salon.tools.studio import (
    ASSET_MIN,
    AVATAR_STALE_DAYS,
    CLAUDEMD_STALE_DAYS,
    avatar_age_days,
    build_cue,
    cid_from_avatar_url,
    classify_media,
    days_since,
    select_recent_media,
)

NOW = 1_700_000_000.0
DAY = 86400.0


def _counts(image=0, audio=0, video=0, other=0) -> dict[str, int]:
    return {"image": image, "audio": audio, "video": video, "other": other}


# --- days_since ---


def test_days_since_floors_and_clamps():
    assert days_since(NOW - 3 * DAY, NOW) == 3
    assert days_since(NOW - 3.9 * DAY, NOW) == 3
    # A future timestamp (clock skew) clamps to 0 rather than going negative.
    assert days_since(NOW + DAY, NOW) == 0


# --- cid_from_avatar_url ---


def test_cid_from_avatar_url_extracts_cid():
    url = "https://cdn.bsky.app/img/avatar/plain/did:plc:abc/bafkreigh2akcid@jpeg"
    assert cid_from_avatar_url(url) == "bafkreigh2akcid"


def test_cid_from_avatar_url_handles_missing():
    assert cid_from_avatar_url(None) is None
    assert cid_from_avatar_url("") is None


# --- select_recent_media / classify_media ---


def test_select_recent_media_dedupes_filters_and_orders():
    paths = [
        "assets/c.png",  # newest
        "",
        "assets/c.png",  # dup of newest
        "notes/scratch.md",  # not media
        "assets/b.wav",
        "assets/a.mp4",
        "assets/old.png",
    ]
    got = select_recent_media(paths, window=3)
    assert got == ["assets/c.png", "assets/b.wav", "assets/a.mp4"]


def test_classify_media_buckets_by_extension():
    counts = classify_media(["a.PNG", "b.jpg", "c.wav", "d.mp4", "e.mov", "f.txt"])
    assert counts == {"image": 2, "audio": 1, "video": 2, "other": 1}


# --- avatar_age_days ---


def test_avatar_age_bootstrap_returns_none_and_stamps_state():
    age, state = avatar_age_days(None, "cid1", NOW)
    assert age is None
    assert state == {"cid": "cid1", "first_seen": NOW}


def test_avatar_age_same_cid_accrues():
    prev = {"cid": "cid1", "first_seen": NOW - 12 * DAY}
    age, state = avatar_age_days(prev, "cid1", NOW)
    assert age == 12
    assert state is prev  # unchanged


def test_avatar_age_change_resets_clock():
    prev = {"cid": "cid1", "first_seen": NOW - 99 * DAY}
    age, state = avatar_age_days(prev, "cid2", NOW)
    assert age is None
    assert state == {"cid": "cid2", "first_seen": NOW}


def test_avatar_age_unknown_cid_leaves_state():
    prev = {"cid": "cid1", "first_seen": NOW - 5 * DAY}
    age, state = avatar_age_days(prev, None, NOW)
    assert age is None
    assert state is prev


def test_avatar_age_corrupt_first_seen_restamps():
    age, state = avatar_age_days({"cid": "cid1", "first_seen": "garbage"}, "cid1", NOW)
    assert age is None
    assert state == {"cid": "cid1", "first_seen": NOW}


# --- build_cue ---


def test_build_cue_empty_when_nothing_fires():
    cue = build_cue(
        claudemd_days=1,
        claudemd_self_edited=True,
        media_counts=_counts(image=2, video=1),
        media_total=3,
        avatar_days=1,
    )
    assert cue == ""


def test_build_cue_flags_never_revised_claudemd():
    cue = build_cue(
        claudemd_days=None,
        claudemd_self_edited=False,
        media_counts=_counts(),
        media_total=0,
        avatar_days=None,
    )
    assert "never revised" in cue
    assert cue.startswith("Studio state")


def test_build_cue_flags_stale_claudemd_only_past_threshold():
    fresh = build_cue(
        claudemd_days=CLAUDEMD_STALE_DAYS - 1,
        claudemd_self_edited=True,
        media_counts=_counts(),
        media_total=0,
        avatar_days=None,
    )
    assert fresh == ""
    stale = build_cue(
        claudemd_days=CLAUDEMD_STALE_DAYS,
        claudemd_self_edited=True,
        media_counts=_counts(),
        media_total=0,
        avatar_days=None,
    )
    assert "last revised your CLAUDE.md" in stale


def test_build_cue_flags_all_image_runs_only():
    all_images = build_cue(
        claudemd_days=1,
        claudemd_self_edited=True,
        media_counts=_counts(image=ASSET_MIN),
        media_total=ASSET_MIN,
        avatar_days=1,
    )
    assert "still images" in all_images
    # A single video in the window suppresses the nudge.
    with_video = build_cue(
        claudemd_days=1,
        claudemd_self_edited=True,
        media_counts=_counts(image=ASSET_MIN - 1, video=1),
        media_total=ASSET_MIN,
        avatar_days=1,
    )
    assert "still images" not in with_video


def test_build_cue_suppresses_media_below_minimum():
    cue = build_cue(
        claudemd_days=1,
        claudemd_self_edited=True,
        media_counts=_counts(image=ASSET_MIN - 1),
        media_total=ASSET_MIN - 1,
        avatar_days=1,
    )
    assert cue == ""


def test_build_cue_flags_stale_avatar():
    cue = build_cue(
        claudemd_days=1,
        claudemd_self_edited=True,
        media_counts=_counts(image=1, video=1),
        media_total=2,
        avatar_days=AVATAR_STALE_DAYS,
    )
    assert "avatar has not changed" in cue
    # None (unknown / freshly changed) never nudges.
    assert "avatar" not in build_cue(
        claudemd_days=1,
        claudemd_self_edited=True,
        media_counts=_counts(image=1, video=1),
        media_total=2,
        avatar_days=None,
    )


def test_main_prints_nothing_without_agent_name(monkeypatch, capsys):
    monkeypatch.delenv("AGENT_NAME", raising=False)
    studio.main()
    assert capsys.readouterr().out == ""
