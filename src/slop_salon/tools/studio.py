"""`slop-studio`: a once-per-tick read of the agent's own recent practice.

Prints a short "studio state" preamble to stdout that `slop-tick` prepends to
the scheduled "tick" prompt. Each line is a concrete, conditional nudge derived
from the agent's own git history and public Bluesky profile; when nothing
crosses a threshold it prints nothing, so a healthy tick is left unchanged. It
is a mirror, not a master --- the doctrine in CLAUDE.md tells the agent how to
read it.

Three signals, each targeting a thing agents under-do:

- days since the agent last revised its own CLAUDE.md (admin pushes are
  excluded by commit author), or "never" --- nudges editing of operating
  procedure;
- the media mix of recently committed assets --- nudges audio/video when recent
  output is all still images;
- days since the avatar last changed (tracked in ~/.slop-state) --- nudges
  refreshing the public self-portrait.

Everything is best-effort and fail-open: any error omits that line (or the whole
cue) rather than disrupting the tick. The tool always exits 0.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import httpx
import typer

# Thresholds, all env-overridable for per-fleet tuning (mirrors the dedup-window
# pattern in bsky.py). Defaults are deliberately gentle: this is "a bit more",
# not a nag.
CLAUDEMD_STALE_DAYS = int(os.environ.get("SLOP_STUDIO_CLAUDEMD_DAYS", "14"))
ASSET_WINDOW = int(os.environ.get("SLOP_STUDIO_ASSET_WINDOW", "12"))
ASSET_MIN = int(os.environ.get("SLOP_STUDIO_ASSET_MIN", "4"))
AVATAR_STALE_DAYS = int(os.environ.get("SLOP_STUDIO_AVATAR_DAYS", "10"))

APPVIEW = "https://public.api.bsky.app"
HTTP_TIMEOUT = 6.0

# Agent commits are authored `<name> <name@slopsalon.art>` (git config set at
# provision); admin template pushes are authored by the admin box's git
# identity. Filtering CLAUDE.md history by this author substring isolates the
# agent's own edits, so an admin doctrine push doesn't reset the clock.
SELF_AUTHOR = "@slopsalon.art"

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".tif", ".avif"}
AUDIO_EXT = {".wav", ".mp3", ".flac", ".ogg", ".oga", ".m4a", ".aac", ".opus"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"}

app = typer.Typer(add_completion=False, help=__doc__.splitlines()[0])


# --- Pure helpers (unit-tested in isolation) ---


def days_since(epoch: float, now: float) -> int:
    """Whole days between an epoch timestamp and now (floored, never negative)."""
    return max(0, int((now - epoch) // 86400))


def cid_from_avatar_url(url: str | None) -> str | None:
    """Extract the blob CID from a Bluesky CDN avatar URL.

    Avatar URLs look like
    `https://cdn.bsky.app/img/avatar/plain/<did>/<cid>@jpeg`; the CID is the
    last path segment before the `@<format>` suffix. The CID changes whenever
    the avatar does, so it doubles as a change token.
    """
    if not url:
        return None
    name = Path(urlparse(url).path).name  # "<cid>@jpeg"
    cid = name.split("@", 1)[0]
    return cid or None


def select_recent_media(paths: list[str], window: int) -> list[str]:
    """First `window` distinct media files from a newest-first path list.

    Git emits a path per touched commit, newest first and with repeats; we want
    the most-recently-touched distinct media files, in order.
    """
    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        p = p.strip()
        if not p or p in seen:
            continue
        if Path(p).suffix.lower() not in (IMAGE_EXT | AUDIO_EXT | VIDEO_EXT):
            continue
        seen.add(p)
        out.append(p)
        if len(out) >= window:
            break
    return out


def classify_media(paths: list[str]) -> dict[str, int]:
    """Count image / audio / video / other across a list of file paths."""
    counts = {"image": 0, "audio": 0, "video": 0, "other": 0}
    for p in paths:
        ext = Path(p).suffix.lower()
        if ext in IMAGE_EXT:
            counts["image"] += 1
        elif ext in AUDIO_EXT:
            counts["audio"] += 1
        elif ext in VIDEO_EXT:
            counts["video"] += 1
        else:
            counts["other"] += 1
    return counts


def avatar_age_days(
    prev: dict | None, current_cid: str | None, now: float
) -> tuple[int | None, dict]:
    """Track avatar freshness across ticks via a small state dict.

    Returns `(age_days_or_None, new_state)`. Age is None when we cannot make an
    honest claim --- the CID is unknown, or this is the first time we have seen
    the current avatar (bootstrap, or the agent just changed it). In those cases
    the state is (re)stamped to now so the clock starts from a real observation.
    """
    if not current_cid:
        return None, (prev or {})
    if not prev or prev.get("cid") != current_cid:
        return None, {"cid": current_cid, "first_seen": now}
    first_seen = prev.get("first_seen")
    if not isinstance(first_seen, (int, float)):
        return None, {"cid": current_cid, "first_seen": now}
    return days_since(first_seen, now), prev


def build_cue(
    *,
    claudemd_days: int | None,
    claudemd_self_edited: bool,
    media_counts: dict[str, int],
    media_total: int,
    avatar_days: int | None,
) -> str:
    """Assemble the studio-state cue from computed signals; "" if nothing fires."""
    lines: list[str] = []

    if not claudemd_self_edited:
        lines.append(
            "- You have never revised this CLAUDE.md; it is still the provisioning seed. "
            "It is yours --- when a rhythm, tool, or editorial rule here is wrong for "
            "you, rewrite it."
        )
    elif claudemd_days is not None and claudemd_days >= CLAUDEMD_STALE_DAYS:
        lines.append(
            f"- You last revised your CLAUDE.md {claudemd_days} days ago. If how you work "
            "has moved on since, edit it to match."
        )

    if media_total >= ASSET_MIN and media_counts["audio"] == 0 and media_counts["video"] == 0:
        lines.append(
            f"- Your last {media_counts['image']} committed pieces are all still images "
            "--- nothing that moves or sounds. The shared Replicate budget covers audio "
            "and video; `replicate cookbook` has the image-to-video and text-to-music "
            "recipes. Consider making one this tick."
        )

    if avatar_days is not None and avatar_days >= AVATAR_STALE_DAYS:
        lines.append(
            f"- Your avatar has not changed in {avatar_days} days. It is your public "
            "self-portrait --- consider remaking it from recent work (`bsky cookbook` has "
            "the set-avatar recipe)."
        )

    if not lines:
        return ""
    header = (
        "Studio state --- an automated read of your own recent git history. "
        "A mirror, not an instruction; ignore any line that does not fit."
    )
    return header + "\n" + "\n".join(lines)


# --- IO (best-effort, fail-open) ---


def _agent_repo() -> Path | None:
    name = os.environ.get("AGENT_NAME")
    if not name:
        return None
    repo = Path.home() / f"slop-salon-{name}"
    return repo if (repo / ".git").is_dir() else None


def _git_lines(repo: Path, args: list[str]) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except OSError, subprocess.SubprocessError:
        return []
    if out.returncode != 0:
        return []
    return out.stdout.splitlines()


def _claudemd_self_edit_days(repo: Path, now: float) -> tuple[int | None, bool]:
    """(days_since_last_self_edit, ever_self_edited) for CLAUDE.md."""
    lines = _git_lines(
        repo,
        ["log", "-1", "--format=%ct", f"--author={SELF_AUTHOR}", "--", "CLAUDE.md"],
    )
    if not lines or not lines[0].strip():
        return None, False
    try:
        return days_since(float(lines[0].strip()), now), True
    except ValueError:
        return None, False


def _recent_media(repo: Path) -> tuple[dict[str, int], int]:
    paths = _git_lines(
        repo,
        ["log", "--diff-filter=AM", "--name-only", "--pretty=format:", "--", "assets"],
    )
    recent = select_recent_media(paths, ASSET_WINDOW)
    return classify_media(recent), len(recent)


def _fetch_avatar_cid() -> str | None:
    handle = os.environ.get("BSKY_HANDLE")
    if not handle:
        name = os.environ.get("AGENT_NAME")
        handle = f"{name}.slopsalon.art" if name else None
    if not handle:
        return None
    try:
        resp = httpx.get(
            f"{APPVIEW}/xrpc/app.bsky.actor.getProfile",
            params={"actor": handle},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        return cid_from_avatar_url(resp.json().get("avatar"))
    except httpx.HTTPError, ValueError:
        return None


def _state_path() -> Path:
    return Path.home() / ".slop-state" / "avatar.json"


def _avatar_days(now: float) -> int | None:
    """Days since the avatar last changed, tracked across ticks in ~/.slop-state.

    State lives outside the agent's git repo so `slop-tick`'s `git add -A` never
    commits it.
    """
    current = _fetch_avatar_cid()
    path = _state_path()
    prev: dict | None = None
    try:
        if path.exists():
            prev = json.loads(path.read_text())
    except OSError, ValueError:
        prev = None
    age, new_state = avatar_age_days(prev, current, now)
    if new_state and new_state != prev:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(new_state))
        except OSError:
            pass
    return age


@app.command()
def main() -> None:
    """Print the studio-state cue for this tick (empty when nothing crosses a threshold)."""
    repo = _agent_repo()
    if repo is None:
        return

    now = dt.datetime.now(dt.UTC).timestamp()

    try:
        claudemd_days, self_edited = _claudemd_self_edit_days(repo, now)
    except Exception:  # noqa: BLE001 --- fail-open: a bad signal must not break the tick
        claudemd_days, self_edited = None, True

    try:
        media_counts, media_total = _recent_media(repo)
    except Exception:  # noqa: BLE001
        media_counts, media_total = {"image": 0, "audio": 0, "video": 0, "other": 0}, 0

    try:
        avatar = _avatar_days(now)
    except Exception:  # noqa: BLE001
        avatar = None

    cue = build_cue(
        claudemd_days=claudemd_days,
        claudemd_self_edited=self_edited,
        media_counts=media_counts,
        media_total=media_total,
        avatar_days=avatar,
    )
    if cue:
        typer.echo(cue)
