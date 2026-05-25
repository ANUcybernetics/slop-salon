"""Ambient-memory recall for agent notebooks.

Sprite-side helper. Reads a query (argv or stdin), ranks lines from
`~/slop-salon-<AGENT_NAME>/notes/**/*.md` by token-set overlap, and
prints the top-K short snippets with their paths.

Invoked from a Claude Code `PostToolUse` hook so prior notebook entries
surface ambiently --- the agent doesn't decide to search; relevant past
work shows up alongside the next tool result. Pattern from Tim Kellogg,
"Ambient Associative Memory" (2026-05-17).

Token-overlap ranking is the poor cousin of BM25, but on a corpus of a
few hundred small markdown files it's fast, dep-free, and good enough as
a starting point. If precision suffers, swap to `rank_bm25` --- the
output format stays the same.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import typer

TOP_K = 3
SNIPPET_WORDS = 12
MIN_TOKEN_LEN = 4
TOKEN_RE = re.compile(rf"\b[a-z]{{{MIN_TOKEN_LEN},}}\b")

app = typer.Typer(add_completion=False, help=__doc__.splitlines()[0])


def _tokens(text: str) -> set[str]:
    return set(TOKEN_RE.findall(text.lower()))


def _notes_dir() -> Path | None:
    name = os.environ.get("AGENT_NAME")
    if not name:
        return None
    path = Path.home() / f"slop-salon-{name}" / "notes"
    return path if path.is_dir() else None


def rank(query: str, notes_dir: Path, top_k: int = TOP_K) -> list[tuple[str, Path]]:
    """Return up to top_k (snippet, path) pairs ranked by token-set overlap."""
    qtoks = _tokens(query)
    if not qtoks:
        return []
    hits: list[tuple[int, str, Path]] = []
    for path in notes_dir.rglob("*.md"):
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            score = len(qtoks & _tokens(line))
            if score == 0:
                continue
            snippet = " ".join(line.split()[:SNIPPET_WORDS])
            hits.append((score, snippet, path))
    hits.sort(key=lambda h: -h[0])
    seen: set[str] = set()
    out: list[tuple[str, Path]] = []
    for _, snippet, path in hits:
        if snippet in seen:
            continue
        seen.add(snippet)
        out.append((snippet, path))
        if len(out) >= top_k:
            break
    return out


@app.command()
def main(
    query: str = typer.Argument(None, help="Query string (omit to read from stdin)"),
):
    """Print top-K notebook snippets matching the query, one per line."""
    if query is None:
        query = sys.stdin.read()
    notes_dir = _notes_dir()
    if notes_dir is None:
        # No notes dir (new agent, or AGENT_NAME unset) --- nothing to surface.
        # Silent exit so the hook doesn't inject an empty block.
        return
    home = Path.home()
    for snippet, path in rank(query, notes_dir):
        try:
            rel = path.relative_to(home)
        except ValueError:
            rel = path
        typer.echo(f'"{snippet}" --- {rel}')
