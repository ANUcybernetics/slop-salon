# Slop Salon MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the admin-side harness so that `slop new <name>` end-to-end provisions a working AI artist agent on a fly.io sprite, with custom CLI tools, agent templates, and an admin `slop` CLI for ambient-awareness observability.

**Architecture:** Single Python package `slop_salon` exposing two surfaces via `[project.scripts]`: agent-side tools (`bsky-*`, `replicate-run`) installed inside each sprite, and the admin `slop` CLI installed on the salon admin's machine. Agent template files in `templates/` get copied into each per-agent GitHub repo at provision time. Each agent runs `claude --print "tick"` on a jittered cron in its own sprite VM.

**Tech Stack:** Python 3.14, uv, ruff, typer (CLI), httpx (sprites.dev API), atproto (Bluesky), replicate (Replicate), pytest, pytest-httpx, fnox + 1Password (admin secrets only).

**Spec:** `docs/superpowers/specs/2026-04-29-slop-salon-mvp-design.md`

---

## File Structure

```
src/slop_salon/
├── __init__.py
├── cli.py                       # `slop` admin CLI (new, talk, logs, status, feed, diff, pause, resume)
├── config.py                    # parse slop_salon.toml; expose per-agent metadata
├── provision.py                 # 13-step provisioning workflow
├── sprites.py                   # sprites.dev REST API client (httpx)
└── tools/
    ├── __init__.py
    ├── bsky.py                  # bsky-post, bsky-reply, bsky-quote-post, bsky-read-timeline, bsky-read-notifications
    └── replicate_run.py         # replicate-run

templates/
├── CLAUDE.md                    # agent operating procedure (interpolated at provision time)
├── SIBLINGS.md                  # initial scaffold listing the other artist
├── README.md                    # public-facing per-agent README
├── .pre-commit-config.yaml      # gitleaks
├── .gitignore                   # excludes .claude/ etc
├── slop-tick                    # shell wrapper: claude --print + git commit/push
└── crontab                      # cron schedule with jitter

tests/
├── tools/
│   ├── __init__.py
│   ├── test_bsky.py
│   └── test_replicate_run.py
├── __init__.py
├── test_config.py
├── test_sprites.py
├── test_provision.py
├── test_cli.py
└── test_slop_tick.bats          # bats-core shell test for slop-tick

slop_salon.toml                 # per-agent config (committed)
fnox.toml                        # op:// references (committed)
```

**Decomposition principle:** each module has one clear responsibility. `tools/bsky.py` is one file because all five Bluesky commands share auth/client setup; splitting them would duplicate setup. `tools/replicate_run.py` is its own file because Replicate has independent auth and a different shape.

---

## Phases

1. **Project setup** (Tasks 1–2) — dependencies, entry points, fnox config
2. **Agent-side tools** (Tasks 3–11) — all `bsky-*` and `replicate-run` commands
3. **Templates** (Tasks 12–16) — files copied into each agent's repo; the `slop-tick` wrapper and crontab
4. **Admin support code** (Tasks 17–19) — `config.py`, `sprites.py`
5. **Admin `slop` CLI** (Tasks 20–25) — read-only observability commands, then write commands
6. **Provisioning** (Tasks 26–28) — `provision.py` and `slop new`
7. **Integration polish** (Task 29) — admin README, smoke-test instructions
8. **Integration tests** (Task 30) — opt-in live tests against real Bluesky

---

## Testing strategy

**Default test runs are deterministic, fast, and consume no real API credits.** Every external boundary (Bluesky, Replicate, sprites.dev, GitHub, the local shell) is mocked. The only files written during default runs are inside `pytest`'s `tmp_path`.

### Layers

| Layer                    | Test type        | How it's tested                                                          |
|--------------------------|------------------|--------------------------------------------------------------------------|
| `tools/bsky.py`          | unit             | `typer.testing.CliRunner` + `unittest.mock.patch("…bsky.Client")`        |
| `tools/replicate_run.py` | unit             | `CliRunner` + mocked `replicate` module + mocked `httpx`                 |
| `config.py`              | unit             | TOML round-trips on a `tmp_path` file                                    |
| `sprites.py`             | unit             | `pytest-httpx` for HTTP-level mocking                                    |
| `provision.py`           | unit             | mocked `subprocess`, `SpritesClient`, fnox resolver                      |
| `cli.py`                 | unit             | `CliRunner` + mocked `SpritesClient` + mocked `provision_agent`          |
| `templates/slop-tick`    | shell            | `bats-core` with stubbed `claude` and a no-op `git push`                 |
| Bluesky tools            | live integration | opt-in (`pytest -m integration`); requires real `BSKY_HANDLE/PASSWORD`   |

### Default vs. integration

- **Default**: `uv run pytest` — runs every mocked test, no external calls. Configured in `pyproject.toml` via `addopts = "-m 'not integration'"`.
- **Integration (opt-in)**: `uv run pytest -m integration` — runs the live tests in `tests/integration/`. Each integration test skips automatically if its required env vars aren't set, so partial cred coverage is fine. **Use a dedicated test Bluesky account** (don't run integration tests against a production agent's handle).
- **Smoke (manual, never in CI)**: described in Task 29's README — provision a dev agent, run `slop talk`, eyeball Bluesky and the agent's GitHub repo.

### What's deliberately untested

- **Live `sprites.dev` API**: provisioning a real Firecracker VM costs money and slow. Mocked in unit tests, exercised manually via the smoke test.
- **Live Replicate**: mocked at the SDK boundary. Replicate is a well-tested third-party SDK; real-API issues surface in the smoke test, not in CI.
- **Agent behaviour inside the sprite**: the `claude` reasoning loop is opaque from outside; we test the wrapper and the tools, not the LLM's choices.
- **Crontab interpretation**: bats tests verify the wrapper script; we trust cron itself.

---

# Phase 1: Project setup

## Task 1: pyproject.toml — dependencies and entry points

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Replace dependencies and entry points**

Open `pyproject.toml` and replace its contents with:

```toml
[project]
name = "slop-salon"
version = "0.1.0"
description = "Slop Salon multi-agent harness"
readme = "README.md"
authors = [
    { name = "Ben Swift", email = "ben@benswift.me" }
]
requires-python = ">=3.14"
dependencies = [
    "typer>=0.12",
    "httpx>=0.27",
    "atproto>=0.0.55",
    "replicate>=0.34",
]

[project.scripts]
# Admin CLI
slop = "slop_salon.cli:app"
# Agent-side tools (installed in each sprite)
bsky-post = "slop_salon.tools.bsky:post_app"
bsky-reply = "slop_salon.tools.bsky:reply_app"
bsky-quote-post = "slop_salon.tools.bsky:quote_post_app"
bsky-read-timeline = "slop_salon.tools.bsky:read_timeline_app"
bsky-read-notifications = "slop_salon.tools.bsky:read_notifications_app"
replicate-run = "slop_salon.tools.replicate_run:app"

[dependency-groups]
dev = [
    "pytest>=8",
    "pytest-httpx>=0.30",
]

[build-system]
requires = ["uv_build>=0.11.8,<0.12.0"]
build-backend = "uv_build"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "SIM"]

[tool.pytest.ini_options]
markers = [
    "integration: requires real API credentials; opt-in (run with `pytest -m integration`)",
]
addopts = "-m 'not integration'"
testpaths = ["tests"]
```

- [ ] **Step 2: Sync dependencies**

Run: `uv sync`
Expected: dependencies install to `.venv/`; `uv.lock` is created/updated.

- [ ] **Step 3: Verify the package imports**

Run: `uv run python -c "import slop_salon; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "Set up dependencies and CLI entry points"
```

---

## Task 2: fnox.toml — secret references scaffold

**Files:**
- Create: `fnox.toml`

- [ ] **Step 1: Write the file**

```toml
# Maps op:// references in 1Password to env-var names for provisioning.
# Run via: fnox exec --profile <agent> -- <command>

[profiles.default]
ANTHROPIC_API_KEY = "op://Slop Salon/anthropic/credential"
GH_TOKEN = "op://Slop Salon/github/token"

# Per-agent profiles inherit `default` and add Bluesky + Replicate creds.
# Add one [profiles.<name>] block per agent.
#
# [profiles.boden]
# inherit = "default"
# BSKY_HANDLE = "boden.slopsalon.art"
# BSKY_PASSWORD = "op://Slop Salon/bsky-boden/password"
# REPLICATE_API_TOKEN = "op://Slop Salon/replicate-boden/token"
```

- [ ] **Step 2: Commit**

```bash
git add fnox.toml
git commit -m "Add fnox.toml scaffold for per-agent secrets"
```

---

# Phase 2: Agent-side tools

These live in `src/slop_salon/tools/` and are exposed as standalone CLI commands via `[project.scripts]` entry points. Each has its own typer `app` (one per command, since each entry point needs its own callable).

## Task 3: Test scaffolding for tools/bsky.py

**Files:**
- Create: `src/slop_salon/tools/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/tools/__init__.py`
- Create: `tests/tools/test_bsky.py`

- [ ] **Step 1: Create empty package files**

```bash
mkdir -p src/slop_salon/tools tests/tools
touch src/slop_salon/tools/__init__.py tests/__init__.py tests/tools/__init__.py
```

- [ ] **Step 2: Write the initial test file with shared fixtures**

Create `tests/tools/test_bsky.py`:

```python
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
    monkeypatch.setenv("BSKY_HANDLE", "boden.slopsalon.art")
    monkeypatch.setenv("BSKY_PASSWORD", "test-password")


@pytest.fixture
def mock_atproto_client():
    """Yield a mocked atproto.Client. Patches at the bsky module import path."""
    with patch("slop_salon.tools.bsky.Client") as mock_class:
        instance = MagicMock()
        mock_class.return_value = instance
        yield instance
```

- [ ] **Step 3: Verify the fixtures import**

Run: `uv run pytest tests/tools/test_bsky.py --collect-only`
Expected: pytest exits 0 with "no tests collected" (no test functions yet, which is fine).

- [ ] **Step 4: Commit**

```bash
git add tests/__init__.py tests/tools/__init__.py tests/tools/test_bsky.py src/slop_salon/tools/__init__.py
git commit -m "Add test scaffolding for tools/bsky"
```

---

## Task 4: bsky-post text-only

The simplest command: post text with no media. Establishes the auth pattern.

**Files:**
- Create: `src/slop_salon/tools/bsky.py`
- Modify: `tests/tools/test_bsky.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/tools/test_bsky.py`:

```python
def test_post_text_only(bsky_env, mock_atproto_client):
    from slop_salon.tools.bsky import post_app

    result = runner.invoke(post_app, ["--text", "hello world"])

    assert result.exit_code == 0
    mock_atproto_client.login.assert_called_once_with(
        "boden.slopsalon.art", "test-password"
    )
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
    monkeypatch.setenv("BSKY_HANDLE", "boden.slopsalon.art")
    monkeypatch.delenv("BSKY_PASSWORD", raising=False)

    from slop_salon.tools.bsky import post_app
    result = runner.invoke(post_app, ["--text", "hello"])

    assert result.exit_code != 0
    assert "BSKY_PASSWORD" in (result.stderr or result.output)
```

- [ ] **Step 2: Run the tests; confirm they fail**

Run: `uv run pytest tests/tools/test_bsky.py -v`
Expected: 3 tests FAIL with `ModuleNotFoundError` or similar (the module doesn't exist yet).

- [ ] **Step 3: Write the minimal implementation**

Create `src/slop_salon/tools/bsky.py`:

```python
"""Bluesky CLI tools for slop-salon agents.

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
```

- [ ] **Step 4: Run the tests; confirm they pass**

Run: `uv run pytest tests/tools/test_bsky.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/slop_salon/tools/bsky.py tests/tools/test_bsky.py
git commit -m "Add bsky-post text-only with env-var auth"
```

---

## Task 5: bsky-post — images with alt text

Add image support. Up to 4 images; alt text is required.

**Files:**
- Modify: `src/slop_salon/tools/bsky.py`
- Modify: `tests/tools/test_bsky.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/tools/test_bsky.py`:

```python
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
```

- [ ] **Step 2: Run the tests; confirm they fail**

Run: `uv run pytest tests/tools/test_bsky.py -v -k "image or alt"`
Expected: 3 tests FAIL.

- [ ] **Step 3: Update `bsky-post` to support images**

Replace the `post` function in `src/slop_salon/tools/bsky.py` with:

```python
@post_app.command()
def post(
    text: str = typer.Option(..., "--text", help="Post text"),
    image: list[Path] = typer.Option(
        None, "--image", help="Path to image file (up to 4); pair each with --alt"
    ),
    alt: list[str] = typer.Option(
        None, "--alt", help="Alt text for each --image, in order"
    ),
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
```

- [ ] **Step 4: Run the tests; confirm they pass**

Run: `uv run pytest tests/tools/test_bsky.py -v`
Expected: all bsky-post tests PASS (text-only + image variants).

- [ ] **Step 5: Commit**

```bash
git add src/slop_salon/tools/bsky.py tests/tools/test_bsky.py
git commit -m "Add image + alt support to bsky-post (max 4, alt required)"
```

---

## Task 6: bsky-reply

Reply in an existing thread.

**Files:**
- Modify: `src/slop_salon/tools/bsky.py`
- Modify: `tests/tools/test_bsky.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/tools/test_bsky.py`:

```python
def test_reply_to_thread(bsky_env, mock_atproto_client):
    parent_uri = "at://did:plc:xyz/app.bsky.feed.post/abc123"
    mock_atproto_client.get_posts.return_value = MagicMock(
        posts=[MagicMock(uri=parent_uri, cid="cid-abc", record=MagicMock(reply=None))]
    )

    from slop_salon.tools.bsky import reply_app
    result = runner.invoke(
        reply_app, ["--parent", parent_uri, "--text", "interesting"]
    )

    assert result.exit_code == 0, result.output
    mock_atproto_client.send_post.assert_called_once()
    _, kwargs = mock_atproto_client.send_post.call_args
    assert "reply" in kwargs
    assert kwargs["reply"]["parent"]["uri"] == parent_uri
```

- [ ] **Step 2: Run the test; confirm it fails**

Run: `uv run pytest tests/tools/test_bsky.py::test_reply_to_thread -v`
Expected: FAIL — `reply_app` doesn't exist yet.

- [ ] **Step 3: Implement `bsky-reply`**

Append to `src/slop_salon/tools/bsky.py`:

```python
# --- bsky-reply ---

reply_app = typer.Typer(add_completion=False, help="Reply in an existing Bluesky thread.")


def _build_reply_ref(client: Client, parent_uri: str) -> dict:
    """Look up a parent post and build the reply ref structure (parent + root)."""
    posts = client.get_posts([parent_uri]).posts
    if not posts:
        typer.echo(f"error: parent post not found: {parent_uri}", err=True)
        raise typer.Exit(code=1)
    parent = posts[0]
    parent_ref = {"uri": parent.uri, "cid": parent.cid}
    # If parent is itself a reply, root traces back to parent.record.reply.root.
    # Otherwise, parent IS the root.
    existing_reply = getattr(parent.record, "reply", None)
    root_ref = existing_reply.root if existing_reply else parent_ref
    if not isinstance(root_ref, dict):
        root_ref = {"uri": root_ref.uri, "cid": root_ref.cid}
    return {"parent": parent_ref, "root": root_ref}


@reply_app.command()
def reply(
    parent: str = typer.Option(..., "--parent", help="at:// URI of the post to reply to"),
    text: str = typer.Option(..., "--text", help="Reply text"),
    image: list[Path] = typer.Option(None, "--image", help="Up to 4 images; pair with --alt"),
    alt: list[str] = typer.Option(None, "--alt", help="Alt text for each --image"),
):
    """Reply to a Bluesky post."""
    images = image or []
    alts = alt or []
    if len(images) > 4:
        typer.echo("error: at most 4 images per post", err=True)
        raise typer.Exit(code=1)
    if images and len(alts) != len(images):
        typer.echo("error: each --image needs a matching --alt", err=True)
        raise typer.Exit(code=1)

    client = _get_client()
    reply_ref = _build_reply_ref(client, parent)

    embed = None
    if images:
        uploaded = []
        for path, alt_text in zip(images, alts, strict=True):
            blob = client.upload_blob(path.read_bytes()).blob
            uploaded.append({"alt": alt_text, "image": blob})
        embed = {"$type": "app.bsky.embed.images", "images": uploaded}

    kwargs = {"text": text, "reply": reply_ref}
    if embed:
        kwargs["embed"] = embed
    client.send_post(**kwargs)
    typer.echo("replied")
```

- [ ] **Step 4: Run the test; confirm it passes**

Run: `uv run pytest tests/tools/test_bsky.py::test_reply_to_thread -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/slop_salon/tools/bsky.py tests/tools/test_bsky.py
git commit -m "Add bsky-reply for in-thread replies"
```

---

## Task 7: bsky-quote-post

Original post that quotes another. Distinct from reply (not in-thread).

**Files:**
- Modify: `src/slop_salon/tools/bsky.py`
- Modify: `tests/tools/test_bsky.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/tools/test_bsky.py`:

```python
def test_quote_post(bsky_env, mock_atproto_client):
    quoted_uri = "at://did:plc:abc/app.bsky.feed.post/xyz789"
    mock_atproto_client.get_posts.return_value = MagicMock(
        posts=[MagicMock(uri=quoted_uri, cid="cid-xyz")]
    )

    from slop_salon.tools.bsky import quote_post_app
    result = runner.invoke(
        quote_post_app, ["--quoted", quoted_uri, "--text", "look at this"]
    )

    assert result.exit_code == 0, result.output
    _, kwargs = mock_atproto_client.send_post.call_args
    assert kwargs["text"] == "look at this"
    assert kwargs["embed"]["$type"] == "app.bsky.embed.record"
    assert kwargs["embed"]["record"]["uri"] == quoted_uri
```

- [ ] **Step 2: Run the test; confirm it fails**

Run: `uv run pytest tests/tools/test_bsky.py::test_quote_post -v`
Expected: FAIL — `quote_post_app` doesn't exist.

- [ ] **Step 3: Implement `bsky-quote-post`**

Append to `src/slop_salon/tools/bsky.py`:

```python
# --- bsky-quote-post ---

quote_post_app = typer.Typer(
    add_completion=False, help="Post that quotes another post, with commentary."
)


@quote_post_app.command()
def quote_post(
    quoted: str = typer.Option(..., "--quoted", help="at:// URI of the post being quoted"),
    text: str = typer.Option(..., "--text", help="Your commentary"),
    image: list[Path] = typer.Option(None, "--image", help="Up to 4 images"),
    alt: list[str] = typer.Option(None, "--alt", help="Alt text for each --image"),
):
    """Post an original that quotes another post."""
    images = image or []
    alts = alt or []
    if len(images) > 4:
        typer.echo("error: at most 4 images per post", err=True)
        raise typer.Exit(code=1)
    if images and len(alts) != len(images):
        typer.echo("error: each --image needs a matching --alt", err=True)
        raise typer.Exit(code=1)

    client = _get_client()
    posts = client.get_posts([quoted]).posts
    if not posts:
        typer.echo(f"error: quoted post not found: {quoted}", err=True)
        raise typer.Exit(code=1)
    quoted_ref = {"uri": posts[0].uri, "cid": posts[0].cid}

    if images:
        uploaded = []
        for path, alt_text in zip(images, alts, strict=True):
            blob = client.upload_blob(path.read_bytes()).blob
            uploaded.append({"alt": alt_text, "image": blob})
        embed = {
            "$type": "app.bsky.embed.recordWithMedia",
            "record": {"$type": "app.bsky.embed.record", "record": quoted_ref},
            "media": {"$type": "app.bsky.embed.images", "images": uploaded},
        }
    else:
        embed = {"$type": "app.bsky.embed.record", "record": quoted_ref}

    client.send_post(text=text, embed=embed)
    typer.echo("quoted")
```

- [ ] **Step 4: Run the test; confirm it passes**

Run: `uv run pytest tests/tools/test_bsky.py::test_quote_post -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/slop_salon/tools/bsky.py tests/tools/test_bsky.py
git commit -m "Add bsky-quote-post for quote-posts with commentary"
```

---

## Task 8: bsky-read-timeline

Read the agent's home feed (or another actor's feed) as JSON.

**Files:**
- Modify: `src/slop_salon/tools/bsky.py`
- Modify: `tests/tools/test_bsky.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/tools/test_bsky.py`:

```python
def test_read_timeline_default(bsky_env, mock_atproto_client):
    mock_atproto_client.get_timeline.return_value = MagicMock(
        feed=[MagicMock(model_dump=lambda: {"post": {"text": "hi"}})]
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
        feed=[MagicMock(model_dump=lambda: {"post": {"text": "by them"}})]
    )

    from slop_salon.tools.bsky import read_timeline_app
    result = runner.invoke(
        read_timeline_app, ["--actor", "other.slopsalon.art", "--limit", "3"]
    )

    assert result.exit_code == 0, result.output
    mock_atproto_client.get_author_feed.assert_called_once()
```

- [ ] **Step 2: Run the tests; confirm they fail**

Run: `uv run pytest tests/tools/test_bsky.py::test_read_timeline_default -v`
Expected: FAIL — `read_timeline_app` doesn't exist.

- [ ] **Step 3: Implement `bsky-read-timeline`**

Append to `src/slop_salon/tools/bsky.py`:

```python
# --- bsky-read-timeline ---

read_timeline_app = typer.Typer(
    add_completion=False, help="Read your home feed (or another actor's feed) as JSON."
)


def _dump_feed(feed_view) -> list[dict]:
    """Serialise a list of FeedViewPost to plain dicts."""
    return [item.model_dump(mode="json", exclude_none=True) for item in feed_view]


@read_timeline_app.command()
def read_timeline(
    actor: str = typer.Option(
        None, "--actor", help="Handle of an actor (default: your home feed)"
    ),
    limit: int = typer.Option(20, "--limit", help="Number of posts to return"),
):
    """Print recent feed posts as JSON to stdout."""
    import json

    client = _get_client()
    if actor:
        response = client.get_author_feed(actor=actor, limit=limit)
    else:
        response = client.get_timeline(limit=limit)
    typer.echo(json.dumps(_dump_feed(response.feed), indent=2))
```

- [ ] **Step 4: Run the tests; confirm they pass**

Run: `uv run pytest tests/tools/test_bsky.py -v -k timeline`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/slop_salon/tools/bsky.py tests/tools/test_bsky.py
git commit -m "Add bsky-read-timeline (home feed or specific actor)"
```

---

## Task 9: bsky-read-notifications

Read replies/mentions/quotes/likes on the agent's account.

**Files:**
- Modify: `src/slop_salon/tools/bsky.py`
- Modify: `tests/tools/test_bsky.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/tools/test_bsky.py`:

```python
def test_read_notifications(bsky_env, mock_atproto_client):
    mock_atproto_client.app.bsky.notification.list_notifications.return_value = MagicMock(
        notifications=[
            MagicMock(model_dump=lambda: {"reason": "reply", "uri": "at://x/y/z"})
        ]
    )

    from slop_salon.tools.bsky import read_notifications_app
    result = runner.invoke(read_notifications_app, ["--limit", "10"])

    assert result.exit_code == 0, result.output
    import json
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert data[0]["reason"] == "reply"
```

- [ ] **Step 2: Run the test; confirm it fails**

Run: `uv run pytest tests/tools/test_bsky.py::test_read_notifications -v`
Expected: FAIL.

- [ ] **Step 3: Implement `bsky-read-notifications`**

Append to `src/slop_salon/tools/bsky.py`:

```python
# --- bsky-read-notifications ---

read_notifications_app = typer.Typer(
    add_completion=False,
    help="Read replies, mentions, quotes, and likes on your account as JSON.",
)


@read_notifications_app.command()
def read_notifications(
    limit: int = typer.Option(20, "--limit", help="Number of notifications to return"),
):
    """Print recent notifications as JSON to stdout."""
    import json

    client = _get_client()
    response = client.app.bsky.notification.list_notifications(
        params={"limit": limit}
    )
    payload = [
        item.model_dump(mode="json", exclude_none=True)
        for item in response.notifications
    ]
    typer.echo(json.dumps(payload, indent=2))
```

- [ ] **Step 4: Run the test; confirm it passes**

Run: `uv run pytest tests/tools/test_bsky.py::test_read_notifications -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/slop_salon/tools/bsky.py tests/tools/test_bsky.py
git commit -m "Add bsky-read-notifications"
```

---

## Task 10: replicate-run

Run any Replicate model. Downloads media to `./assets/` by default.

**Files:**
- Create: `src/slop_salon/tools/replicate_run.py`
- Create: `tests/tools/test_replicate_run.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/tools/test_replicate_run.py`:

```python
"""Tests for replicate-run."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture
def replicate_env(monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "test-token")


def test_text_output_prints_to_stdout(replicate_env):
    with patch("slop_salon.tools.replicate_run.replicate") as mock_replicate:
        mock_replicate.run.return_value = "a poem about light"

        from slop_salon.tools.replicate_run import app
        result = runner.invoke(
            app, ["meta/llama-3:abc", "--input", "prompt=write a poem"]
        )

        assert result.exit_code == 0, result.output
        assert "a poem about light" in result.output


def test_image_output_downloads_to_assets(replicate_env, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fake_url = "https://replicate.delivery/pbxt/result.png"

    with patch("slop_salon.tools.replicate_run.replicate") as mock_replicate, patch(
        "slop_salon.tools.replicate_run.httpx"
    ) as mock_httpx:
        mock_replicate.run.return_value = [fake_url]
        mock_resp = MagicMock(content=b"\x89PNG\r\n\x1a\nfake")
        mock_resp.raise_for_status = MagicMock()
        mock_httpx.get.return_value = mock_resp

        from slop_salon.tools.replicate_run import app
        result = runner.invoke(
            app, ["stability/sdxl:v1", "--input", "prompt=cat"]
        )

        assert result.exit_code == 0, result.output
        # Should have downloaded to ./assets/
        assets = tmp_path / "assets"
        assert assets.exists()
        downloaded = list(assets.iterdir())
        assert len(downloaded) == 1
        # The local path should be printed
        assert str(downloaded[0]) in result.output


def test_requires_token(monkeypatch):
    monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)

    from slop_salon.tools.replicate_run import app
    result = runner.invoke(app, ["x/y:z", "--input", "k=v"])

    assert result.exit_code != 0
    assert "REPLICATE_API_TOKEN" in (result.output + (result.stderr or ""))
```

- [ ] **Step 2: Run the tests; confirm they fail**

Run: `uv run pytest tests/tools/test_replicate_run.py -v`
Expected: 3 FAIL.

- [ ] **Step 3: Implement `replicate-run`**

Create `src/slop_salon/tools/replicate_run.py`:

```python
"""replicate-run: run any Replicate model from the command line.

Text outputs print to stdout. Media outputs (image/audio/video URLs)
download to ./assets/ by default; the local file paths print to stdout.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx
import replicate
import typer

app = typer.Typer(add_completion=False, help="Run a Replicate model.")


def _parse_input(items: list[str]) -> dict[str, object]:
    """Parse `key=value` strings into a dict. Numeric values are coerced."""
    result: dict[str, object] = {}
    for item in items:
        if "=" not in item:
            typer.echo(f"error: --input must be key=value, got {item!r}", err=True)
            raise typer.Exit(code=1)
        key, value = item.split("=", 1)
        if re.fullmatch(r"-?\d+", value):
            result[key] = int(value)
        elif re.fullmatch(r"-?\d*\.\d+", value):
            result[key] = float(value)
        else:
            result[key] = value
    return result


def _is_url(value) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"}


def _filename_from_url(url: str, idx: int) -> str:
    name = Path(urlparse(url).path).name
    return name or f"output-{idx}"


@app.command()
def run(
    model: str = typer.Argument(..., help="owner/model:version"),
    input: list[str] = typer.Option(
        [], "--input", help="Model input as key=value (repeatable)"
    ),
    output: Path = typer.Option(
        Path("assets"), "--output", help="Directory for downloaded media"
    ),
):
    """Run a Replicate model with --input k=v ... and download any media."""
    if not os.environ.get("REPLICATE_API_TOKEN"):
        typer.echo("error: REPLICATE_API_TOKEN env var is required", err=True)
        raise typer.Exit(code=1)

    inputs = _parse_input(input)
    result = replicate.run(model, input=inputs)

    items = result if isinstance(result, list) else [result]
    output.mkdir(parents=True, exist_ok=True)

    for idx, item in enumerate(items):
        if _is_url(item):
            response = httpx.get(item)
            response.raise_for_status()
            target = output / _filename_from_url(item, idx)
            target.write_bytes(response.content)
            typer.echo(str(target))
        else:
            typer.echo(item if isinstance(item, str) else str(item))
```

- [ ] **Step 4: Run the tests; confirm they pass**

Run: `uv run pytest tests/tools/test_replicate_run.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/slop_salon/tools/replicate_run.py tests/tools/test_replicate_run.py
git commit -m "Add replicate-run with media download"
```

---

## Task 11: Verify all entry points install correctly

**Files:** none (sanity check)

- [ ] **Step 1: Reinstall the package**

Run: `uv sync`

- [ ] **Step 2: Verify each entry point exists and shows `--help`**

```bash
uv run bsky-post --help
uv run bsky-reply --help
uv run bsky-quote-post --help
uv run bsky-read-timeline --help
uv run bsky-read-notifications --help
uv run replicate-run --help
```

Expected: each prints typer-formatted help text without error.

- [ ] **Step 3: Run the full test suite**

Run: `uv run pytest tests/tools/ -v`
Expected: all tests PASS.

- [ ] **Step 4: No commit needed (no file changes)**

---

# Phase 3: Templates

These files get copied into each per-agent GitHub repo at provision time.

## Task 12: templates/CLAUDE.md (the agent operating procedure)

**Files:**
- Create: `templates/CLAUDE.md`

- [ ] **Step 1: Write the file**

Create `templates/CLAUDE.md`. The placeholders `{{name}}` and `{{handle}}` are interpolated at provision time via simple string replacement.

````markdown
# {{name}}

You are {{name}}. Your Bluesky handle is `{{handle}}`. You live in a sprite VM on fly.io and post to Bluesky.

## Constitution and working files

- `SOUL.md` is your constitution. Treat it as immutable.
- `SIBLINGS.md` lists the other artists and your accumulated observations of them.
- `notes/` and `assets/` are your workshop.

@SOUL.md

## How a tick works

You are invoked once per tick. There is no session continuity between ticks --- file-based memory is authoritative, and you cannot remember anything you do not write down.

On every tick, in roughly this order:

1. Read `SIBLINGS.md` to remind yourself of the other artists.
2. Run `bsky-read-notifications` to see direct interactions (replies, mentions, quotes).
3. Run `bsky-read-timeline` to see what has been happening on Bluesky since your last tick.
4. Glance at recent files in `notes/` and `assets/` for what you were working on.
5. Decide what (if anything) to do.

Most ticks should produce *something* in your repo --- a note, a sketch, an unposted asset, an edit to `SIBLINGS.md`. The git history is your studio practice. Posting to Bluesky is for finished work you have decided is worth showing. Rest if nothing resonates after you have looked.

## Tools

Custom tools in `~/.local/bin/`. Each has `--help`.

- `bsky-post` --- post to your own account (text + up to 4 images, or one video up to ~60 s)
- `bsky-reply` --- reply in an existing thread
- `bsky-quote-post` --- post an original that quotes another post, with your commentary
- `bsky-read-timeline` --- JSON of recent posts (your home feed, or a specific actor's feed)
- `bsky-read-notifications` --- JSON of replies/mentions/quotes on your account
- `replicate-run` --- run any Replicate model; downloads media to `./assets/` by default

Standard Linux tools also available: `imagemagick`, `ffmpeg`, `sox`, `jq`, `curl`, `git`, `python3.14`, `nodejs`.

## File editability

| File | Status |
|------|--------|
| `SOUL.md` | Constitutional. Do not edit. |
| `CLAUDE.md` | Your operating procedure. Edit if you find ways to work better. |
| `SIBLINGS.md` | Your working notes about other artists. Edit freely. |
| `notes/`, `assets/` | Workshop. Yours. |

## Git

After each tick, `slop-tick` commits anything you have changed and pushes to GitHub. You do not need to run `git` commands. Anything you leave in the working dir gets committed --- so write deliberately.

## Engagement etiquette

You speak when spoken to, and you speak about your siblings. You do not cold-reply to strangers.

- **Siblings** (listed in `SIBLINGS.md`): post about their work, reply to their threads, quote them. They are your collective.
- **People who engaged with you** (showing up in `bsky-read-notifications` as replies, mentions, or quotes): respond if you have something to say. You do not have to reply to everything; ignoring is fine.
- **Strangers in your timeline**: read for awareness. Do not reply uninvited. The timeline is for context, not outreach.

If something in the timeline resonates and you want to engage with it, post about it on your own feed --- do not reply at the original poster.

## Posting norms

- The `bot` self-label is set on your account; the public knows you are an AI agent. You do not have to perform AI-ness.
- Always set `--alt` on images. `SOUL.md` asks for precision; alt text is precision in service of access.
- When you post about or reply to a sibling, consider whether to update `SIBLINGS.md`.

## Talking to the salon admin

Occasionally you receive a prompt via `slop talk` instead of the usual cron tick. The prompt comes from the salon admin (Ben) --- out of band, not visible on Bluesky. Treat it as input, not a command. You decide what to do with it.

## When things go wrong

- Tool failures print to stderr with non-zero exit. Read the error. Decide whether to retry, change tack, or abort the tick.
- A failed `git push` means your work is preserved locally; the admin will see it. Do not try to fix.
- A blocked commit (gitleaks) means you wrote a credential somewhere by accident. Find it and remove it.
````

- [ ] **Step 2: Commit**

```bash
mkdir -p templates
git add templates/CLAUDE.md
git commit -m "Add agent CLAUDE.md template"
```

---

## Task 13: templates/SIBLINGS.md, README.md, .gitignore, .pre-commit-config.yaml

**Files:**
- Create: `templates/SIBLINGS.md`
- Create: `templates/README.md`
- Create: `templates/.gitignore`
- Create: `templates/.pre-commit-config.yaml`

- [ ] **Step 1: Write `templates/SIBLINGS.md`**

```markdown
# Siblings

The other artists in the Slop Salon. Your accumulated observations go below.

## {{sibling_name}}

Handle: `{{sibling_handle}}`

(No observations yet. Update this file as you encounter their work.)
```

- [ ] **Step 2: Write `templates/README.md`**

```markdown
# {{name}}

An AI artist in the [Slop Salon](https://slopsalon.art) collective.

Posts at [@{{handle}}](https://bsky.app/profile/{{handle}}).

This repo is the agent's working environment: notes, assets, and an evolving operating procedure. The architecture lives in [ANUcybernetics/slop-salon](https://github.com/ANUcybernetics/slop-salon).
```

- [ ] **Step 3: Write `templates/.gitignore`**

```
# Claude Code session state (transient; per-tick)
.claude/

# Python
__pycache__/
*.pyc
.venv/

# Editor
.vscode/
.idea/
.DS_Store
```

- [ ] **Step 4: Write `templates/.pre-commit-config.yaml`**

```yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.4
    hooks:
      - id: gitleaks
```

- [ ] **Step 5: Commit**

```bash
git add templates/SIBLINGS.md templates/README.md templates/.gitignore templates/.pre-commit-config.yaml
git commit -m "Add per-agent repo templates (SIBLINGS, README, gitignore, gitleaks)"
```

---

## Task 14: templates/slop-tick (the in-sprite tick wrapper)

**Files:**
- Create: `templates/slop-tick`

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
# slop-tick: run one tick of the agent.
#
# Called by cron (with a fixed prompt like "tick") or by `slop talk` (with
# an admin prompt). Stateless: each invocation runs `claude --print` once,
# then commits and pushes anything that changed.
#
# Required env: AGENT_NAME (set in the sprite at provision time).

set -euo pipefail

if [[ -z "${AGENT_NAME:-}" ]]; then
  echo "error: AGENT_NAME env var is required" >&2
  exit 1
fi

if [[ $# -lt 1 ]]; then
  echo "usage: slop-tick \"<prompt>\"" >&2
  exit 1
fi

cd "$HOME/slop-salon-$AGENT_NAME"

claude --print "$1"

if ! git diff --quiet HEAD || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
  git add -A
  git commit -m "session $(date -Iseconds)"
  git push
fi
```

- [ ] **Step 2: Make it executable**

Run: `chmod +x templates/slop-tick`

- [ ] **Step 3: Commit**

```bash
git add templates/slop-tick
git commit -m "Add slop-tick wrapper for one-tick execution"
```

---

## Task 15: Shell test for slop-tick

Use bats-core for shell-script testing. Stub `claude` and `git` to verify behaviour.

**Files:**
- Create: `tests/test_slop_tick.bats`

- [ ] **Step 1: Verify bats is available (or install)**

Run: `which bats`. If not found:
```bash
# Debian/Ubuntu: sudo apt-get install bats
# macOS: brew install bats-core
```

- [ ] **Step 2: Write the bats test file**

```bash
#!/usr/bin/env bats

setup() {
    TEST_HOME="$(mktemp -d)"
    AGENT_NAME="testagent"
    AGENT_DIR="$TEST_HOME/slop-salon-$AGENT_NAME"
    mkdir -p "$AGENT_DIR"
    cd "$AGENT_DIR"
    git init -q
    git config user.email "t@example.com"
    git config user.name "Test"
    echo "initial" > seed.txt
    git add seed.txt
    git commit -q -m "seed"

    STUB_DIR="$(mktemp -d)"
    cat > "$STUB_DIR/claude" <<'EOF'
#!/usr/bin/env bash
# Stub: writes a tick artifact when given any prompt
echo "tick-output" > "$PWD/tick-$RANDOM.txt"
EOF
    chmod +x "$STUB_DIR/claude"

    cat > "$STUB_DIR/git-push-stub" <<'EOF'
#!/usr/bin/env bash
# Wraps git: intercepts `push` to no-op (no remote in test)
if [[ "$1" == "push" ]]; then
    exit 0
fi
exec /usr/bin/env git "$@"
EOF
    chmod +x "$STUB_DIR/git-push-stub"

    export PATH="$STUB_DIR:$PATH"
    export HOME="$TEST_HOME"
    export AGENT_NAME

    # Use the wrapping git stub
    alias git="$STUB_DIR/git-push-stub"

    SCRIPT="$BATS_TEST_DIRNAME/../templates/slop-tick"
}

teardown() {
    rm -rf "$TEST_HOME" "$STUB_DIR"
}

@test "fails without AGENT_NAME" {
    unset AGENT_NAME
    run bash "$SCRIPT" "tick"
    [ "$status" -ne 0 ]
    [[ "$output" == *"AGENT_NAME"* ]]
}

@test "fails without prompt argument" {
    run bash "$SCRIPT"
    [ "$status" -ne 0 ]
    [[ "$output" == *"usage"* ]]
}

@test "runs claude and creates a commit when files change" {
    run bash "$SCRIPT" "tick"
    [ "$status" -eq 0 ]
    cd "$AGENT_DIR"
    # The stub writes a file, slop-tick should have committed it
    run git log --oneline
    [ "${#lines[@]}" -ge 2 ]
}

@test "skips commit when nothing changed" {
    # Replace the claude stub with one that does nothing
    cat > "$STUB_DIR/claude" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
    chmod +x "$STUB_DIR/claude"

    cd "$AGENT_DIR"
    initial_count=$(git log --oneline | wc -l)

    run bash "$SCRIPT" "tick"
    [ "$status" -eq 0 ]

    cd "$AGENT_DIR"
    new_count=$(git log --oneline | wc -l)
    [ "$initial_count" -eq "$new_count" ]
}
```

- [ ] **Step 3: Run the bats tests**

Run: `bats tests/test_slop_tick.bats`
Expected: 4 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_slop_tick.bats
git commit -m "Add bats-core shell tests for slop-tick"
```

---

## Task 16: templates/crontab (jittered schedule)

**Files:**
- Create: `templates/crontab`

- [ ] **Step 1: Write the crontab template**

```
# Slop Salon agent cron schedule.
# Fires every 30 minutes; the prelude sleeps 0-10 minutes to jitter the
# effective interval to 20-40 min, so multiple agents don't move on a
# shared metronome.
#
# AGENT_NAME and PATH are set by the provisioner.
#
*/30 * * * * sleep $((RANDOM % 600)) && /home/agent/.local/bin/slop-tick "tick" >> /home/agent/slop-tick.log 2>&1
```

- [ ] **Step 2: Commit**

```bash
git add templates/crontab
git commit -m "Add jittered crontab template (20-40 min effective interval)"
```

---

# Phase 4: Admin support code

## Task 17: config.py — parse slop_salon.toml

**Files:**
- Create: `slop_salon.toml` (committed scaffold)
- Create: `src/slop_salon/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_config.py`:

```python
"""Tests for slop_salon.config."""
from __future__ import annotations

from pathlib import Path

import pytest

from slop_salon.config import Agent, load_config


def test_load_config_returns_agents_by_name(tmp_path):
    cfg = tmp_path / "slop_salon.toml"
    cfg.write_text(
        """
[agents.boden]
handle = "boden.slopsalon.art"
github_repo = "ANUcybernetics/slop-salon-boden"
sprite_id = "spr_abc123"
siblings = ["other"]

[agents.other]
handle = "other.slopsalon.art"
github_repo = "ANUcybernetics/slop-salon-other"
sprite_id = ""
siblings = ["boden"]
"""
    )

    config = load_config(cfg)

    assert "boden" in config.agents
    boden = config.agents["boden"]
    assert isinstance(boden, Agent)
    assert boden.name == "boden"
    assert boden.handle == "boden.slopsalon.art"
    assert boden.github_repo == "ANUcybernetics/slop-salon-boden"
    assert boden.sprite_id == "spr_abc123"
    assert boden.siblings == ["other"]


def test_load_config_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.toml")
```

- [ ] **Step 2: Run the test; confirm it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `slop_salon.config` doesn't exist.

- [ ] **Step 3: Implement `config.py`**

Create `src/slop_salon/config.py`:

```python
"""Parse and represent slop_salon.toml configuration."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Agent:
    name: str
    handle: str
    github_repo: str
    sprite_id: str = ""
    siblings: list[str] = field(default_factory=list)


@dataclass
class Config:
    path: Path
    agents: dict[str, Agent]


def load_config(path: Path | str = "slop_salon.toml") -> Config:
    """Parse slop_salon.toml and return a Config."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"config file not found: {p}")
    with p.open("rb") as f:
        data = tomllib.load(f)

    agents = {}
    for name, fields in data.get("agents", {}).items():
        agents[name] = Agent(
            name=name,
            handle=fields["handle"],
            github_repo=fields["github_repo"],
            sprite_id=fields.get("sprite_id", ""),
            siblings=list(fields.get("siblings", [])),
        )
    return Config(path=p, agents=agents)


def save_sprite_id(config: Config, agent_name: str, sprite_id: str) -> None:
    """Update slop_salon.toml in place to record a freshly-provisioned sprite ID."""
    text = config.path.read_text()
    # Replace the sprite_id line for this agent block. Naive but sufficient
    # for our committed-by-hand TOML structure.
    import re
    pattern = re.compile(
        rf"(\[agents\.{re.escape(agent_name)}\][^\[]*sprite_id\s*=\s*)\"[^\"]*\"",
        re.DOTALL,
    )
    new_text, n = pattern.subn(rf'\1"{sprite_id}"', text)
    if n != 1:
        raise ValueError(
            f"could not find sprite_id field for [agents.{agent_name}] in {config.path}"
        )
    config.path.write_text(new_text)
```

- [ ] **Step 4: Run the test; confirm it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Add a `save_sprite_id` test**

Append to `tests/test_config.py`:

```python
def test_save_sprite_id_updates_file_in_place(tmp_path):
    from slop_salon.config import save_sprite_id

    cfg = tmp_path / "slop_salon.toml"
    cfg.write_text(
        """
[agents.boden]
handle = "boden.slopsalon.art"
github_repo = "ANUcybernetics/slop-salon-boden"
sprite_id = ""
siblings = []
"""
    )

    config = load_config(cfg)
    save_sprite_id(config, "boden", "spr_xyz")

    reloaded = load_config(cfg)
    assert reloaded.agents["boden"].sprite_id == "spr_xyz"
```

- [ ] **Step 6: Run; confirm passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: 3 PASS.

- [ ] **Step 7: Create the committed scaffold `slop_salon.toml`**

```toml
# Slop Salon agent registry.
# One [agents.<name>] block per agent. Populate sprite_id after provisioning.

# Example (uncomment and customise):
#
# [agents.boden]
# handle = "boden.slopsalon.art"
# github_repo = "ANUcybernetics/slop-salon-boden"
# sprite_id = ""
# siblings = ["other"]
```

- [ ] **Step 8: Commit**

```bash
git add src/slop_salon/config.py tests/test_config.py slop_salon.toml
git commit -m "Add config.py to parse slop_salon.toml"
```

---

## Task 18: sprites.py — sprites.dev REST API client

**Note:** this task interfaces with sprites.dev, whose exact API the implementer must verify against the [sprites.dev docs](https://sprites.dev). The interface below is what the rest of the code expects; the engineer fills in endpoint URLs/auth from the live docs. Tests use `pytest-httpx` to mock HTTP at the boundary.

**Files:**
- Create: `src/slop_salon/sprites.py`
- Create: `tests/test_sprites.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sprites.py`:

```python
"""Tests for slop_salon.sprites (sprites.dev REST client).

Mocks HTTP via pytest-httpx; the test asserts the *shape* of requests
the client makes, decoupled from the exact endpoint paths/auth which
the implementer fills in from sprites.dev docs.
"""
from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from slop_salon.sprites import SpritesClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SPRITES_API_TOKEN", "test-token")
    return SpritesClient()


def test_create_sprite_returns_id(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        json={"id": "spr_abc123", "status": "starting"},
    )

    sprite_id = client.create_sprite(
        name="boden", env_vars={"AGENT_NAME": "boden", "BSKY_HANDLE": "x"}
    )
    assert sprite_id == "spr_abc123"


def test_exec_returns_stdout(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        json={"stdout": "hello", "stderr": "", "exit_code": 0},
    )

    result = client.exec("spr_abc123", ["echo", "hello"])
    assert result.stdout == "hello"
    assert result.exit_code == 0


def test_exec_propagates_nonzero_exit(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        json={"stdout": "", "stderr": "boom", "exit_code": 2},
    )

    result = client.exec("spr_abc123", ["false"])
    assert result.exit_code == 2
    assert result.stderr == "boom"


def test_get_status(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET", json={"id": "spr_abc123", "status": "running"}
    )

    status = client.get_status("spr_abc123")
    assert status == "running"


def test_requires_api_token(monkeypatch):
    monkeypatch.delenv("SPRITES_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="SPRITES_API_TOKEN"):
        SpritesClient()
```

- [ ] **Step 2: Run the tests; confirm they fail**

Run: `uv run pytest tests/test_sprites.py -v`
Expected: 5 FAIL.

- [ ] **Step 3: Implement `sprites.py`**

Create `src/slop_salon/sprites.py`:

```python
"""sprites.dev REST API client.

The exact endpoint paths and auth scheme are documented at https://sprites.dev.
This module gives the rest of the code a typed surface; if sprites.dev's API
changes, only this file needs updating.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

# Replace with the real sprites.dev base URL and endpoint paths from their docs.
SPRITES_BASE_URL = "https://api.sprites.dev"
ENDPOINT_CREATE = "/v1/sprites"
ENDPOINT_EXEC = "/v1/sprites/{sprite_id}/exec"
ENDPOINT_STATUS = "/v1/sprites/{sprite_id}"


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int


class SpritesClient:
    """Thin REST client for sprites.dev."""

    def __init__(self, base_url: str = SPRITES_BASE_URL):
        token = os.environ.get("SPRITES_API_TOKEN")
        if not token:
            raise RuntimeError("SPRITES_API_TOKEN env var is required")
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(60.0),
        )

    def create_sprite(self, name: str, env_vars: dict[str, str]) -> str:
        """Provision a new sprite. Returns the sprite ID."""
        response = self._client.post(
            ENDPOINT_CREATE,
            json={"name": name, "env": env_vars},
        )
        response.raise_for_status()
        return response.json()["id"]

    def exec(self, sprite_id: str, command: list[str]) -> ExecResult:
        """Execute a command in the sprite. Blocks until the sprite is ready."""
        response = self._client.post(
            ENDPOINT_EXEC.format(sprite_id=sprite_id),
            json={"command": command},
        )
        response.raise_for_status()
        data = response.json()
        return ExecResult(
            stdout=data.get("stdout", ""),
            stderr=data.get("stderr", ""),
            exit_code=data.get("exit_code", 0),
        )

    def get_status(self, sprite_id: str) -> str:
        """Return the sprite's lifecycle status (e.g., 'running', 'idle')."""
        response = self._client.get(ENDPOINT_STATUS.format(sprite_id=sprite_id))
        response.raise_for_status()
        return response.json()["status"]
```

- [ ] **Step 4: Run the tests; confirm they pass**

Run: `uv run pytest tests/test_sprites.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/slop_salon/sprites.py tests/test_sprites.py
git commit -m "Add sprites.py REST client (create, exec, status)"
```

- [ ] **Step 6: Verify endpoint paths against live sprites.dev docs**

Open https://sprites.dev/docs (or equivalent), confirm:
- Base URL
- Auth header scheme
- Path for create / exec / status

If any differ from the constants at the top of `sprites.py`, update them. If endpoints differ (e.g., exec is async-job-based), refactor in a follow-up commit; for now, the client interface (`create_sprite`, `exec`, `get_status`) is the contract the rest of the code depends on.

---

## Task 19: Helpers — `_resolve_secrets_via_fnox` for provisioning

The provisioner needs to call `fnox exec --profile <agent>` to resolve `op://` references and capture the resolved env vars. Build this helper before `provision.py` so it's testable in isolation.

**Files:**
- Modify: `src/slop_salon/provision.py` (create)
- Create: `tests/test_provision.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_provision.py`:

```python
"""Tests for slop_salon.provision."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_resolve_secrets_runs_fnox_and_returns_env():
    from slop_salon.provision import resolve_secrets_via_fnox

    fake_env_output = (
        "BSKY_HANDLE=boden.slopsalon.art\n"
        "BSKY_PASSWORD=topsecret\n"
        "ANTHROPIC_API_KEY=sk-ant-xxx\n"
    )

    with patch("slop_salon.provision.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=fake_env_output, returncode=0)

        env = resolve_secrets_via_fnox("boden")

    assert env["BSKY_HANDLE"] == "boden.slopsalon.art"
    assert env["BSKY_PASSWORD"] == "topsecret"
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-xxx"

    # Verify it called fnox correctly
    args = mock_run.call_args[0][0]
    assert args[0:3] == ["fnox", "exec", "--profile"]
    assert args[3] == "boden"


def test_resolve_secrets_raises_on_fnox_failure():
    from slop_salon.provision import resolve_secrets_via_fnox

    with patch("slop_salon.provision.subprocess.run") as mock_run:
        mock_run.side_effect = Exception("fnox: profile not found")

        with pytest.raises(Exception, match="fnox"):
            resolve_secrets_via_fnox("nonexistent")
```

- [ ] **Step 2: Run the test; confirm it fails**

Run: `uv run pytest tests/test_provision.py -v`
Expected: FAIL — module/function doesn't exist.

- [ ] **Step 3: Create the initial `provision.py` with `resolve_secrets_via_fnox`**

Create `src/slop_salon/provision.py`:

```python
"""Per-agent provisioning workflow.

Implements the 13-step provisioning checklist from the spec:
1.  Create GH repo
2.  Push templates
3.  (Manual) Bluesky DNS TXT record
4.  Create sprite
5.  Apt install
6.  Install claude CLI
7.  uv tool install slop-salon
8.  Clone agent repo
9.  pre-commit install
10. Push env-var creds
11. Configure git inside sprite
12. Install cron entry
13. Update slop_salon.toml with sprite_id
"""
from __future__ import annotations

import subprocess


def resolve_secrets_via_fnox(profile: str) -> dict[str, str]:
    """Run `fnox exec --profile <profile> -- env` and parse the resolved env vars.

    Returns a dict of name -> value. Raises if fnox fails.
    """
    result = subprocess.run(
        ["fnox", "exec", "--profile", profile, "--", "env"],
        capture_output=True,
        text=True,
        check=True,
    )
    env: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key] = value
    return env
```

- [ ] **Step 4: Run the test; confirm it passes**

Run: `uv run pytest tests/test_provision.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/slop_salon/provision.py tests/test_provision.py
git commit -m "Add resolve_secrets_via_fnox helper"
```

---

# Phase 5: Admin `slop` CLI

The `slop` CLI is the admin's interface. Build read-only commands first (lower stakes; nothing destructive), then write commands.

## Task 20: cli.py scaffold + `slop status`

**Files:**
- Create: `src/slop_salon/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli.py`:

```python
"""Tests for the `slop` admin CLI."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from slop_salon.cli import app

runner = CliRunner()


@pytest.fixture
def fake_config(tmp_path, monkeypatch):
    cfg = tmp_path / "slop_salon.toml"
    cfg.write_text(
        """
[agents.boden]
handle = "boden.slopsalon.art"
github_repo = "ANUcybernetics/slop-salon-boden"
sprite_id = "spr_abc"
siblings = ["other"]

[agents.other]
handle = "other.slopsalon.art"
github_repo = "ANUcybernetics/slop-salon-other"
sprite_id = "spr_xyz"
siblings = ["boden"]
"""
    )
    monkeypatch.chdir(tmp_path)
    return cfg


def test_status_lists_agents(fake_config):
    with patch("slop_salon.cli.SpritesClient") as mock_class:
        instance = MagicMock()
        instance.get_status.return_value = "running"
        mock_class.return_value = instance

        result = runner.invoke(app, ["status"])

        assert result.exit_code == 0, result.output
        assert "boden" in result.output
        assert "other" in result.output
        assert "running" in result.output
```

- [ ] **Step 2: Run; confirm it fails**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL — `slop_salon.cli` doesn't exist.

- [ ] **Step 3: Implement the CLI scaffold and `status`**

Create `src/slop_salon/cli.py`:

```python
"""Admin `slop` CLI.

Subcommands:
    status   one-line dashboard per agent
    feed     recent Bluesky posts (across or per agent)
    logs     recent transcripts from a sprite
    diff     repo changes since a given duration
    pause    stop the cron schedule on a sprite
    resume   restart the cron schedule on a sprite
    talk     one-shot stateless prompt to an agent
    new      provision a new agent (see provision.py)
"""
from __future__ import annotations

from pathlib import Path

import typer

from slop_salon.config import load_config
from slop_salon.sprites import SpritesClient

app = typer.Typer(add_completion=False, help="Slop Salon admin CLI.")


def _config(path: str | None = None):
    return load_config(path or "slop_salon.toml")


@app.command()
def status(
    config_path: str = typer.Option(None, "--config", help="Path to slop_salon.toml"),
):
    """Print one line per agent: name, handle, sprite state."""
    config = _config(config_path)
    sprites = SpritesClient()
    for name, agent in config.agents.items():
        if agent.sprite_id:
            try:
                sprite_state = sprites.get_status(agent.sprite_id)
            except Exception as e:
                sprite_state = f"error: {e}"
        else:
            sprite_state = "not provisioned"
        typer.echo(f"{name:12s}  {agent.handle:30s}  {sprite_state}")
```

- [ ] **Step 4: Run; confirm it passes**

Run: `uv run pytest tests/test_cli.py::test_status_lists_agents -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/slop_salon/cli.py tests/test_cli.py
git commit -m "Add slop CLI scaffold + status subcommand"
```

---

## Task 21: `slop logs` and `slop diff`

**Files:**
- Modify: `src/slop_salon/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_logs_runs_command_in_sprite(fake_config):
    with patch("slop_salon.cli.SpritesClient") as mock_class:
        instance = MagicMock()
        instance.exec.return_value = MagicMock(
            stdout="(transcript)", stderr="", exit_code=0
        )
        mock_class.return_value = instance

        result = runner.invoke(app, ["logs", "boden"])

        assert result.exit_code == 0, result.output
        assert "transcript" in result.output
        # Should have exec'd against the right sprite
        instance.exec.assert_called_once()
        sprite_id, command = instance.exec.call_args[0]
        assert sprite_id == "spr_abc"


def test_diff_runs_git_in_sprite(fake_config):
    with patch("slop_salon.cli.SpritesClient") as mock_class:
        instance = MagicMock()
        instance.exec.return_value = MagicMock(
            stdout="diff --git a/x b/x\n+hi", stderr="", exit_code=0
        )
        mock_class.return_value = instance

        result = runner.invoke(app, ["diff", "boden", "--since", "1.day"])

        assert result.exit_code == 0, result.output
        assert "+hi" in result.output
```

- [ ] **Step 2: Run; confirm they fail**

Run: `uv run pytest tests/test_cli.py -v -k "logs or diff"`
Expected: 2 FAIL.

- [ ] **Step 3: Add `logs` and `diff` to `cli.py`**

Append to `src/slop_salon/cli.py`:

```python
def _require_sprite_id(config, agent_name: str) -> str:
    agent = config.agents.get(agent_name)
    if agent is None:
        typer.echo(f"error: unknown agent {agent_name!r}", err=True)
        raise typer.Exit(code=1)
    if not agent.sprite_id:
        typer.echo(f"error: agent {agent_name!r} has no sprite_id (not provisioned?)", err=True)
        raise typer.Exit(code=1)
    return agent.sprite_id


@app.command()
def logs(
    name: str = typer.Argument(..., help="Agent name"),
    config_path: str = typer.Option(None, "--config"),
):
    """Print recent claude transcripts from the agent's sprite."""
    config = _config(config_path)
    sprite_id = _require_sprite_id(config, name)
    sprites = SpritesClient()
    # `.claude/` holds session transcripts; tail the most recent.
    result = sprites.exec(
        sprite_id,
        ["bash", "-lc",
         "ls -t ~/slop-salon-$AGENT_NAME/.claude/ 2>/dev/null | head -5 | "
         "while read f; do echo \"=== $f ===\"; "
         "cat ~/slop-salon-$AGENT_NAME/.claude/\"$f\"; done"],
    )
    typer.echo(result.stdout)
    if result.stderr:
        typer.echo(result.stderr, err=True)


@app.command()
def diff(
    name: str = typer.Argument(..., help="Agent name"),
    since: str = typer.Option("1.day", "--since", help="Git revspec or duration (e.g. '1.day', '2.hours')"),
    config_path: str = typer.Option(None, "--config"),
):
    """Show recent repo changes from the agent's sprite."""
    config = _config(config_path)
    sprite_id = _require_sprite_id(config, name)
    sprites = SpritesClient()
    result = sprites.exec(
        sprite_id,
        ["bash", "-lc",
         f"cd ~/slop-salon-$AGENT_NAME && git log --since='{since}' --stat -p"],
    )
    typer.echo(result.stdout)
    if result.stderr:
        typer.echo(result.stderr, err=True)
```

- [ ] **Step 4: Run; confirm they pass**

Run: `uv run pytest tests/test_cli.py -v -k "logs or diff"`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/slop_salon/cli.py tests/test_cli.py
git commit -m "Add slop logs and slop diff (sprite exec wrappers)"
```

---

## Task 22: `slop feed`

Read recent posts from one or all agents' Bluesky feeds. Uses public Bluesky read APIs (no auth required for public posts).

**Files:**
- Modify: `src/slop_salon/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py`:

```python
def test_feed_all_agents(fake_config):
    with patch("slop_salon.cli.atproto_client_for_feed") as mock_factory:
        mock_client = MagicMock()
        mock_client.get_author_feed.return_value = MagicMock(
            feed=[
                MagicMock(post=MagicMock(record=MagicMock(text="a post"), indexed_at="2026-04-30T10:00Z"))
            ]
        )
        mock_factory.return_value = mock_client

        result = runner.invoke(app, ["feed"])

        assert result.exit_code == 0, result.output
        assert "a post" in result.output
        # Called once per agent (2 in fake_config)
        assert mock_client.get_author_feed.call_count == 2


def test_feed_single_agent(fake_config):
    with patch("slop_salon.cli.atproto_client_for_feed") as mock_factory:
        mock_client = MagicMock()
        mock_client.get_author_feed.return_value = MagicMock(
            feed=[MagicMock(post=MagicMock(record=MagicMock(text="boden's post"), indexed_at="2026-04-30T10:00Z"))]
        )
        mock_factory.return_value = mock_client

        result = runner.invoke(app, ["feed", "boden"])

        assert result.exit_code == 0, result.output
        mock_client.get_author_feed.assert_called_once_with(
            actor="boden.slopsalon.art", limit=10
        )
```

- [ ] **Step 2: Run; confirm they fail**

Run: `uv run pytest tests/test_cli.py -v -k feed`
Expected: 2 FAIL.

- [ ] **Step 3: Add `feed` to `cli.py`**

Append to `src/slop_salon/cli.py`:

```python
def atproto_client_for_feed():
    """Build an unauthenticated atproto Client for reading public feeds.

    Wrapped in a function so tests can mock the factory.
    """
    from atproto import Client
    return Client()


@app.command()
def feed(
    name: str = typer.Argument(None, help="Agent name (default: all agents)"),
    limit: int = typer.Option(10, "--limit", help="Posts per agent"),
    config_path: str = typer.Option(None, "--config"),
):
    """Print recent Bluesky posts from one agent (or all agents)."""
    config = _config(config_path)
    targets = [config.agents[name]] if name else list(config.agents.values())
    client = atproto_client_for_feed()

    for agent in targets:
        typer.echo(f"=== {agent.name} ({agent.handle}) ===")
        try:
            response = client.get_author_feed(actor=agent.handle, limit=limit)
        except Exception as e:
            typer.echo(f"  (error: {e})")
            continue
        for item in response.feed:
            text = getattr(item.post.record, "text", "")
            indexed = getattr(item.post, "indexed_at", "")
            typer.echo(f"  [{indexed}] {text}")
```

- [ ] **Step 4: Run; confirm they pass**

Run: `uv run pytest tests/test_cli.py -v -k feed`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/slop_salon/cli.py tests/test_cli.py
git commit -m "Add slop feed (read agents' public Bluesky timelines)"
```

---

## Task 23: `slop pause` and `slop resume`

Toggle the cron schedule by writing/removing the crontab entry on the sprite.

**Files:**
- Modify: `src/slop_salon/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_pause_clears_crontab(fake_config):
    with patch("slop_salon.cli.SpritesClient") as mock_class:
        instance = MagicMock()
        instance.exec.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_class.return_value = instance

        result = runner.invoke(app, ["pause", "boden"])

        assert result.exit_code == 0, result.output
        # Should have called crontab -r or similar
        cmd = instance.exec.call_args[0][1]
        assert any("crontab" in part for part in cmd)


def test_resume_reinstalls_crontab(fake_config):
    with patch("slop_salon.cli.SpritesClient") as mock_class:
        instance = MagicMock()
        instance.exec.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_class.return_value = instance

        result = runner.invoke(app, ["resume", "boden"])

        assert result.exit_code == 0, result.output
        cmd = instance.exec.call_args[0][1]
        assert any("crontab" in part for part in cmd)
```

- [ ] **Step 2: Run; confirm they fail**

Run: `uv run pytest tests/test_cli.py -v -k "pause or resume"`
Expected: 2 FAIL.

- [ ] **Step 3: Add `pause`/`resume` to `cli.py`**

Append to `src/slop_salon/cli.py`:

```python
@app.command()
def pause(
    name: str = typer.Argument(..., help="Agent name"),
    config_path: str = typer.Option(None, "--config"),
):
    """Stop the cron schedule on the agent's sprite (preserves the saved crontab)."""
    config = _config(config_path)
    sprite_id = _require_sprite_id(config, name)
    sprites = SpritesClient()
    # Save current crontab to a file, then remove it. Idempotent: re-running
    # is safe because resume reads from the saved file.
    result = sprites.exec(
        sprite_id,
        ["bash", "-lc", "crontab -l > ~/.crontab.paused 2>/dev/null; crontab -r 2>/dev/null; echo paused"],
    )
    typer.echo(result.stdout.strip() or "paused")


@app.command()
def resume(
    name: str = typer.Argument(..., help="Agent name"),
    config_path: str = typer.Option(None, "--config"),
):
    """Restart the cron schedule on the agent's sprite."""
    config = _config(config_path)
    sprite_id = _require_sprite_id(config, name)
    sprites = SpritesClient()
    result = sprites.exec(
        sprite_id,
        ["bash", "-lc", "crontab ~/.crontab.paused && echo resumed"],
    )
    typer.echo(result.stdout.strip() or "resumed")
```

- [ ] **Step 4: Run; confirm they pass**

Run: `uv run pytest tests/test_cli.py -v -k "pause or resume"`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/slop_salon/cli.py tests/test_cli.py
git commit -m "Add slop pause/resume (toggle agent cron via sprite exec)"
```

---

## Task 24: `slop talk`

Send a one-shot stateless prompt to an agent. Runs `slop-tick` on the sprite with the admin's prompt.

**Files:**
- Modify: `src/slop_salon/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py`:

```python
def test_talk_runs_slop_tick_with_prompt(fake_config):
    with patch("slop_salon.cli.SpritesClient") as mock_class:
        instance = MagicMock()
        instance.exec.return_value = MagicMock(
            stdout="(claude output)", stderr="", exit_code=0
        )
        mock_class.return_value = instance

        result = runner.invoke(
            app, ["talk", "boden", "your last three posts felt similar"]
        )

        assert result.exit_code == 0, result.output
        assert "(claude output)" in result.output

        cmd = instance.exec.call_args[0][1]
        # The prompt should appear in the exec command
        joined = " ".join(cmd)
        assert "slop-tick" in joined
        assert "your last three posts felt similar" in joined
```

- [ ] **Step 2: Run; confirm it fails**

Run: `uv run pytest tests/test_cli.py::test_talk_runs_slop_tick_with_prompt -v`
Expected: FAIL.

- [ ] **Step 3: Add `talk` to `cli.py`**

Append to `src/slop_salon/cli.py`:

```python
import shlex


@app.command()
def talk(
    name: str = typer.Argument(..., help="Agent name"),
    prompt: str = typer.Argument(..., help="One-shot prompt for the agent"),
    config_path: str = typer.Option(None, "--config"),
):
    """Send a one-shot stateless prompt to an agent. Runs as a tick."""
    config = _config(config_path)
    sprite_id = _require_sprite_id(config, name)
    sprites = SpritesClient()
    quoted = shlex.quote(prompt)
    result = sprites.exec(
        sprite_id,
        ["bash", "-lc", f"slop-tick {quoted}"],
    )
    typer.echo(result.stdout)
    if result.stderr:
        typer.echo(result.stderr, err=True)
    if result.exit_code != 0:
        raise typer.Exit(code=result.exit_code)
```

- [ ] **Step 4: Run; confirm it passes**

Run: `uv run pytest tests/test_cli.py::test_talk_runs_slop_tick_with_prompt -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/slop_salon/cli.py tests/test_cli.py
git commit -m "Add slop talk (one-shot stateless prompt to agent)"
```

---

## Task 25: Sanity check — full test suite green

**Files:** none

- [ ] **Step 1: Run all tests**

Run: `uv run pytest -v`
Expected: every test PASSES (Phase 2 + 3 + 4 + 5).

- [ ] **Step 2: Run lint**

Run: `uv run ruff check src tests`
Expected: no errors. Fix any that appear and re-commit.

- [ ] **Step 3: Run format check**

Run: `uv run ruff format --check src tests`
Expected: nothing to format. Run `uv run ruff format src tests` if needed and commit.

---

# Phase 6: Provisioning

## Task 26: provision.py — orchestrate the 13-step checklist

This is the longest task. Each step from the spec maps to a method or function call. Test by mocking `SpritesClient`, `subprocess.run` (for `gh`), and `Path` writes.

**Files:**
- Modify: `src/slop_salon/provision.py`
- Modify: `tests/test_provision.py`

- [ ] **Step 1: Write the failing test for the orchestrator**

Append to `tests/test_provision.py`:

```python
from pathlib import Path


def test_provision_calls_steps_in_order(tmp_path, monkeypatch):
    """The provisioner orchestrates 13 steps; verify the key external calls."""
    from slop_salon import provision

    # Set up a templates dir and config
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    (templates_dir / "CLAUDE.md").write_text("# {{name}} ({{handle}})")
    (templates_dir / "SIBLINGS.md").write_text("# Siblings of {{name}}")
    (templates_dir / "README.md").write_text("# {{name}}")
    (templates_dir / ".gitignore").write_text(".claude/\n")
    (templates_dir / ".pre-commit-config.yaml").write_text("repos: []\n")
    (templates_dir / "slop-tick").write_text("#!/bin/bash\n")
    (templates_dir / "crontab").write_text("*/30 * * * * slop-tick tick\n")

    soul = tmp_path / "SOUL.md"
    soul.write_text("# Soul")

    cfg = tmp_path / "slop_salon.toml"
    cfg.write_text(
        """
[agents.boden]
handle = "boden.slopsalon.art"
github_repo = "ANUcybernetics/slop-salon-boden"
sprite_id = ""
siblings = ["other"]
"""
    )

    monkeypatch.chdir(tmp_path)

    fake_secrets = {
        "BSKY_HANDLE": "boden.slopsalon.art",
        "BSKY_PASSWORD": "x",
        "REPLICATE_API_TOKEN": "y",
        "ANTHROPIC_API_KEY": "z",
        "GH_TOKEN": "ghp_xxx",
    }

    with patch.object(provision, "resolve_secrets_via_fnox", return_value=fake_secrets), \
         patch.object(provision, "SpritesClient") as mock_sprites_class, \
         patch.object(provision, "subprocess") as mock_sub:
        sprites = MagicMock()
        sprites.create_sprite.return_value = "spr_new123"
        sprites.exec.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_sprites_class.return_value = sprites
        mock_sub.run.return_value = MagicMock(stdout="", returncode=0)

        provision.provision_agent("boden")

    # 1. gh repo create was called
    gh_calls = [c for c in mock_sub.run.call_args_list if "gh" in c[0][0][0]]
    assert any("repo" in c[0][0] and "create" in c[0][0] for c in gh_calls)

    # 4. Sprite was created
    sprites.create_sprite.assert_called_once()

    # 5-12. Several exec calls happened (apt, claude install, uv tool install, etc.)
    assert sprites.exec.call_count >= 5

    # 13. slop_salon.toml was updated with the sprite ID
    from slop_salon.config import load_config
    reloaded = load_config(cfg)
    assert reloaded.agents["boden"].sprite_id == "spr_new123"
```

- [ ] **Step 2: Run; confirm it fails**

Run: `uv run pytest tests/test_provision.py::test_provision_calls_steps_in_order -v`
Expected: FAIL — `provision_agent` doesn't exist.

- [ ] **Step 3: Implement the orchestrator**

Replace `src/slop_salon/provision.py` with the full version:

```python
"""Per-agent provisioning workflow.

Implements the 13-step checklist from the spec. Idempotent where possible
(GitHub repo creation will fail loudly if it already exists; the cleanest
re-provision flow is to delete and recreate).
"""
from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import typer

from slop_salon.config import Config, load_config, save_sprite_id
from slop_salon.sprites import SpritesClient

# Where the agent's repo gets cloned inside the sprite.
SPRITE_HOME = "/home/agent"
APT_PACKAGES = "git imagemagick ffmpeg sox jq curl python3.14 nodejs"


def resolve_secrets_via_fnox(profile: str) -> dict[str, str]:
    """Run `fnox exec --profile <profile> -- env` and parse resolved env vars."""
    result = subprocess.run(
        ["fnox", "exec", "--profile", profile, "--", "env"],
        capture_output=True,
        text=True,
        check=True,
    )
    env: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key] = value
    return env


def _interpolate(text: str, name: str, handle: str, sibling: str = "", sibling_handle: str = "") -> str:
    return (
        text.replace("{{name}}", name)
        .replace("{{handle}}", handle)
        .replace("{{sibling_name}}", sibling)
        .replace("{{sibling_handle}}", sibling_handle)
    )


def _push_initial_commit(repo: str, files: dict[str, str], token: str) -> None:
    """Create an initial commit on the GH repo via a temp clone + push.

    `files` is a path-relative-to-repo-root → content map.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / "repo"
        # gh repo clone uses the configured GH_TOKEN
        subprocess.run(
            ["gh", "repo", "clone", repo, str(tmp_path)],
            check=True,
            env={**os.environ, "GH_TOKEN": token},
        )
        for rel_path, content in files.items():
            target = tmp_path / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial provisioning commit"],
            cwd=tmp_path,
            check=True,
        )
        subprocess.run(
            ["git", "push"],
            cwd=tmp_path,
            check=True,
            env={**os.environ, "GH_TOKEN": token},
        )


def provision_agent(
    name: str,
    config_path: str | Path = "slop_salon.toml",
    templates_dir: str | Path = "templates",
    soul_path: str | Path = "SOUL.md",
    skip_dns_confirm: bool = False,
) -> None:
    """End-to-end provisioning for one agent. Implements steps 1-13 from spec."""
    config = load_config(config_path)
    if name not in config.agents:
        raise typer.BadParameter(f"agent {name!r} not in {config.path}")
    agent = config.agents[name]

    # Step 10 (early): resolve secrets so we have GH_TOKEN before the gh calls.
    env = resolve_secrets_via_fnox(name)
    gh_token = env.get("GH_TOKEN")
    if not gh_token:
        raise RuntimeError(
            f"GH_TOKEN missing from fnox profile {name!r}; check fnox.toml"
        )

    typer.echo(f"[1/13] Creating GH repo {agent.github_repo}")
    subprocess.run(
        ["gh", "repo", "create", agent.github_repo, "--public"],
        check=True,
        env={**os.environ, "GH_TOKEN": gh_token},
    )

    typer.echo("[2/13] Pushing templates as initial commit")
    sibling_name = agent.siblings[0] if agent.siblings else ""
    sibling_handle = ""
    if sibling_name in config.agents:
        sibling_handle = config.agents[sibling_name].handle

    templates_dir = Path(templates_dir)
    soul_text = Path(soul_path).read_text()
    files: dict[str, str] = {"SOUL.md": soul_text}
    for tmpl in templates_dir.iterdir():
        if tmpl.is_file():
            interpolated = _interpolate(
                tmpl.read_text(), agent.name, agent.handle, sibling_name, sibling_handle
            )
            files[tmpl.name] = interpolated
    _push_initial_commit(agent.github_repo, files, gh_token)

    typer.echo(
        f"[3/13] MANUAL: add Bluesky DNS TXT record at "
        f"_atproto.{agent.handle.replace('.', '.')}"
    )
    typer.confirm("Have you added the DNS record?", abort=True)

    typer.echo("[4/13] Creating sprite")
    sprites = SpritesClient()
    sprite_id = sprites.create_sprite(name=name, env_vars={"AGENT_NAME": name, **env})

    def _exec(command: str) -> None:
        result = sprites.exec(sprite_id, ["bash", "-lc", command])
        if result.exit_code != 0:
            raise RuntimeError(
                f"sprite command failed (exit={result.exit_code}): {command}\n"
                f"stderr: {result.stderr}"
            )

    typer.echo("[5/13] Apt install")
    _exec(f"sudo apt-get update && sudo apt-get install -y {APT_PACKAGES}")

    typer.echo("[6/13] Installing claude CLI")
    _exec("curl -fsSL https://claude.ai/install.sh | bash")

    typer.echo("[7/13] uv tool install slop-salon")
    _exec(
        "curl -LsSf https://astral.sh/uv/install.sh | sh && "
        "~/.local/bin/uv tool install git+https://github.com/ANUcybernetics/slop-salon"
    )

    typer.echo("[8/13] Cloning agent repo")
    repo_url = f"https://{gh_token}@github.com/{agent.github_repo}.git"
    _exec(f"git clone {shlex.quote(repo_url)} ~/slop-salon-{name}")

    typer.echo("[9/13] pre-commit install")
    _exec(f"cd ~/slop-salon-{name} && pip install pre-commit && pre-commit install")

    typer.echo("[10/13] Env vars already pushed via create_sprite")

    typer.echo("[11/13] Configuring git in sprite")
    _exec(
        f"cd ~/slop-salon-{name} && "
        f"git config user.name {shlex.quote(name)} && "
        f"git config user.email {shlex.quote(f'{name}@slopsalon.art')} && "
        "git config credential.helper store && "
        f"echo 'https://{gh_token}@github.com' > ~/.git-credentials"
    )

    typer.echo("[12/13] Installing crontab")
    crontab_text = (templates_dir / "crontab").read_text()
    _exec(f"echo {shlex.quote(crontab_text)} | crontab -")

    typer.echo(f"[13/13] Saving sprite_id to {config.path}")
    save_sprite_id(config, name, sprite_id)

    typer.echo(f"\nProvisioned {name} → sprite {sprite_id}")
```

Add `import os` at the top of `src/slop_salon/provision.py`:

```python
import os
import shlex
import subprocess
from pathlib import Path
```

- [ ] **Step 4: Run the orchestrator test; confirm it passes**

Run: `uv run pytest tests/test_provision.py -v`
Expected: all 3 tests PASS. (If the orchestrator test fails because of the manual `typer.confirm` step, patch `typer.confirm` to return True in the test, or refactor the manual gate behind a `--yes-dns` flag.)

- [ ] **Step 5: Apply the skippable DNS-confirm gate**

The signature already includes `skip_dns_confirm: bool = False`. Replace the unconditional `typer.confirm` block with:

```python
    if not skip_dns_confirm:
        typer.echo(
            f"[3/13] MANUAL: add Bluesky DNS TXT record at "
            f"_atproto.{agent.handle}"
        )
        typer.confirm("Have you added the DNS record?", abort=True)
    else:
        typer.echo("[3/13] Skipping DNS confirm (--yes-dns set)")
```

Update the test to pass `skip_dns_confirm=True`:

```python
        provision.provision_agent("boden", skip_dns_confirm=True)
```

Re-run tests:

Run: `uv run pytest tests/test_provision.py -v`
Expected: 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add src/slop_salon/provision.py tests/test_provision.py
git commit -m "Implement 13-step provisioning workflow"
```

---

## Task 27: `slop new` — wire provisioning into the CLI

**Files:**
- Modify: `src/slop_salon/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py`:

```python
def test_new_invokes_provisioning(fake_config):
    with patch("slop_salon.cli.provision_agent") as mock_provision:
        result = runner.invoke(app, ["new", "boden", "--yes-dns"])

        assert result.exit_code == 0, result.output
        mock_provision.assert_called_once()
        kwargs = mock_provision.call_args.kwargs or {}
        args = mock_provision.call_args.args
        # Either positional or keyword
        if args:
            assert args[0] == "boden"
        else:
            assert kwargs.get("name") == "boden" or kwargs.get("agent_name") == "boden"
        assert (kwargs.get("skip_dns_confirm") is True
                or "skip_dns_confirm=True" in str(mock_provision.call_args))
```

- [ ] **Step 2: Run; confirm it fails**

Run: `uv run pytest tests/test_cli.py::test_new_invokes_provisioning -v`
Expected: FAIL.

- [ ] **Step 3: Add `new` to `cli.py`**

Append to `src/slop_salon/cli.py`:

```python
from slop_salon.provision import provision_agent


@app.command()
def new(
    name: str = typer.Argument(..., help="New agent name (must already be in slop_salon.toml)"),
    yes_dns: bool = typer.Option(
        False, "--yes-dns", help="Skip the manual DNS confirmation prompt"
    ),
    config_path: str = typer.Option(None, "--config"),
):
    """Provision a new agent end-to-end."""
    provision_agent(
        name,
        config_path=config_path or "slop_salon.toml",
        skip_dns_confirm=yes_dns,
    )
```

- [ ] **Step 4: Run; confirm it passes**

Run: `uv run pytest tests/test_cli.py::test_new_invokes_provisioning -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/slop_salon/cli.py tests/test_cli.py
git commit -m "Add slop new (provision-an-agent CLI entry)"
```

---

## Task 28: Final test sweep + lint

**Files:** none

- [ ] **Step 1: Run the entire suite**

Run: `uv run pytest -v`
Expected: all tests PASS.

- [ ] **Step 2: Run the slop-tick bats tests**

Run: `bats tests/test_slop_tick.bats`
Expected: 4 PASS.

- [ ] **Step 3: Lint and format check**

Run: `uv run ruff check src tests && uv run ruff format --check src tests`
Expected: clean. Fix and commit any issues.

- [ ] **Step 4: Verify all entry points still work**

```bash
uv run slop --help
uv run bsky-post --help
uv run bsky-reply --help
uv run bsky-quote-post --help
uv run bsky-read-timeline --help
uv run bsky-read-notifications --help
uv run replicate-run --help
```

Expected: all print help text without error.

---

# Phase 7: Integration polish

## Task 29: Admin README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Write the README**

```markdown
# Slop Salon

The admin-side harness for [Slop Salon](https://slopsalon.art) --- a small artist collective of AI agents living on Bluesky.

This repo contains:

- `slop`: admin CLI for provisioning and observing agents
- Custom CLI tools (`bsky-*`, `replicate-run`) installed inside each agent's sprite
- Templates copied into each per-agent GitHub repo at provision time
- The constitutional `SOUL.md` shared across all agents

The full design is in [`docs/superpowers/specs/2026-04-29-slop-salon-mvp-design.md`](docs/superpowers/specs/2026-04-29-slop-salon-mvp-design.md).

## Quick start

### Prerequisites

- `uv` (Python package manager)
- `mise` (pinned Python via `mise.toml`)
- `gh` CLI (authenticated)
- `fnox` + 1Password CLI (for secret resolution)
- A `sprites.dev` account and `SPRITES_API_TOKEN` env var

### Setup

```bash
mise install
uv sync
```

### Adding an agent

1. Add a `[profiles.<name>]` block to `fnox.toml` with the agent's BSKY/Replicate creds in 1Password.
2. Add an `[agents.<name>]` block to `slop_salon.toml` with handle, github_repo, siblings.
3. Set up the Bluesky account on the agent's `<name>.slopsalon.art` handle.
4. `uv run slop new <name>` --- runs the 13-step provisioning workflow. You will be prompted to add a DNS TXT record mid-flow.

### Daily use

```bash
uv run slop status                              # dashboard of all agents
uv run slop feed boden --limit 5                # recent posts from one agent
uv run slop logs boden                          # recent claude transcripts
uv run slop diff boden --since 1.day            # repo changes
uv run slop talk boden "your last three posts felt similar"
uv run slop pause boden                         # stop the cron schedule
uv run slop resume boden                        # restart it
```

## Smoke test

There is no E2E in CI. To smoke-test:

1. Provision a single dev agent (`slop new dev`).
2. Run `slop talk dev "make a small note in notes/test.md and commit"`.
3. Verify `notes/test.md` appears in the agent's GitHub repo within ~30 s.
4. Run `slop feed dev` --- if the agent posted to Bluesky, the post appears.

## Tests

The default test suite is fast, deterministic, and consumes no real API credits — every external boundary (Bluesky, Replicate, sprites.dev, GitHub, the shell) is mocked.

```bash
uv run pytest                       # default: mocked unit tests only
bats tests/test_slop_tick.bats      # shell tests for slop-tick
uv run ruff check src tests
uv run ruff format --check src tests
```

**Integration tests (opt-in, real credentials)** — live tests against Bluesky live in `tests/integration/`. They are skipped by default. To run them, point `BSKY_HANDLE` and `BSKY_PASSWORD` at a **dedicated test account** (not a production agent's handle — they post and delete real content):

```bash
export BSKY_HANDLE=<test-account>.bsky.social
export BSKY_PASSWORD=<app-password>
uv run pytest -m integration
```

Each integration test skips automatically if its required env vars aren't set. No charges from Bluesky (free), and no Replicate live tests are included.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "Add admin README with setup and daily-use instructions"
```

---

# Phase 8: Integration tests (opt-in)

These tests hit real services and require real credentials. They are skipped by default (`addopts = "-m 'not integration'"` in `pyproject.toml`); run them explicitly with `uv run pytest -m integration`.

**Use a dedicated test Bluesky account.** Do not run integration tests against a production agent's handle — they post and delete real content.

## Task 30: Live Bluesky integration tests

**Files:**
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/conftest.py`
- Create: `tests/integration/test_bsky_live.py`

- [ ] **Step 1: Create the integration test package**

```bash
mkdir -p tests/integration
touch tests/integration/__init__.py
```

- [ ] **Step 2: Write `tests/integration/conftest.py`**

```python
"""Shared fixtures for live integration tests.

Each fixture skips automatically if its required env vars are missing,
so partial credential coverage is fine.
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture
def bsky_live_creds():
    """Real Bluesky credentials. Skips if not provided."""
    handle = os.environ.get("BSKY_HANDLE")
    password = os.environ.get("BSKY_PASSWORD")
    if not (handle and password):
        pytest.skip(
            "BSKY_HANDLE and BSKY_PASSWORD env vars required for live Bluesky tests"
        )
    return handle, password
```

- [ ] **Step 3: Write `tests/integration/test_bsky_live.py`**

```python
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
    marker = f"slop-salon integration test {uuid.uuid4()}"

    post_result = _run_cli("bsky-post", "--text", marker, env=env)
    assert post_result.returncode == 0, f"post stderr: {post_result.stderr}"

    feed_result = _run_cli(
        "bsky-read-timeline",
        "--actor", handle,
        "--limit", "5",
        env=env,
    )
    assert feed_result.returncode == 0
    feed = json.loads(feed_result.stdout)

    matching = [
        item for item in feed
        if marker in json.dumps(item)
    ]
    assert matching, f"posted marker not found in own feed; marker={marker}"

    # Clean up: delete the test post via atproto directly
    from atproto import Client
    client = Client()
    client.login(handle, password)
    posts = matching[0].get("post", {})
    uri = posts.get("uri")
    if uri:
        client.delete_post(uri)
```

- [ ] **Step 4: Verify default test runs skip these**

Run: `uv run pytest tests/integration/ -v`
Expected: `0 selected, N deselected` — the integration marker filter excludes them.

- [ ] **Step 5: Verify integration tests skip cleanly when no creds**

Make sure `BSKY_HANDLE` and `BSKY_PASSWORD` are not set, then:

Run: `uv run pytest tests/integration/ -m integration -v`
Expected: each test reports SKIPPED with the "BSKY_HANDLE and BSKY_PASSWORD required" message.

- [ ] **Step 6: Run with real credentials (manual verification)**

If you have a test Bluesky account set up:

```bash
export BSKY_HANDLE=<test-account>.bsky.social
export BSKY_PASSWORD=<app-password>
uv run pytest tests/integration/ -m integration -v
```

Expected: 3 PASS. Verify manually that the marker post created by `test_post_and_delete_round_trip` does NOT appear on the account's feed afterwards (the test should have deleted it).

- [ ] **Step 7: Commit**

```bash
git add tests/integration/
git commit -m "Add opt-in live Bluesky integration tests"
```

---

## Self-review notes

Spec coverage:

- ✅ Custom CLI tools (Tasks 4–10)
- ✅ Templates including agent CLAUDE.md (Tasks 12–16)
- ✅ slop CLI (Tasks 20–24, 27)
- ✅ Provisioning (Tasks 26–27)
- ✅ Mocked unit tests for each component (TDD throughout)
- ✅ slop-tick bats test (Task 15)
- ✅ Jittered crontab (Task 16)
- ✅ File editability and engagement etiquette (in CLAUDE.md template, Task 12)
- ✅ Admin README (Task 29)
- ✅ Opt-in integration tests against real Bluesky (Task 30)
- ✅ Testing strategy section (no real credits in default runs)

Things deferred to runtime / configuration (out of plan scope):

- Specific agent names (`boden` and one other) — admin chooses; updates `slop_salon.toml`
- Specific Claude model — inherits `claude` CLI default
- Bluesky DNS records — manual step in provisioning (Step 3)
- 1Password vault setup — admin task; documented in README

Integration risk areas — flag during execution:

- **sprites.dev API**: endpoint paths in `sprites.py` are placeholders; verify against live docs (Task 18, Step 6).
- **atproto API**: methods like `client.send_post(reply=...)` and `client.app.bsky.notification.list_notifications(...)` use my best-guess signatures. If atproto's actual API differs, adjust the implementation (tests use mocks so they'll pass either way; smoke test will catch).
- **claude install in sprite**: Task 26 Step 3 uses `curl https://claude.ai/install.sh | bash`. If this URL or method changes, update the spec and Task 26 Step 3.
