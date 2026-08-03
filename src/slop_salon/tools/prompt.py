"""Render the agent's operating procedure for whichever runner is driving it.

Sprite-side helper. Claude Code reads `CLAUDE.md` and expands `@file` lines into
it, which is how `SOUL.md`, `MEMORY.md` and `TOOLS.md` reach every tick without
the agent having to remember to read them. Codex reads `AGENTS.md` and has no
import syntax at all, so on the codex runner those three files would silently
vanish from the prompt --- the same failure mode as the oversize `SIBLINGS.md`
that broke a tick step on all six agents for weeks, and just as quiet.

So on a codex tick, `slop-tick` runs `slop-prompt agents-md` first: it expands
the imports itself and writes a flat `AGENTS.md`. Generated per tick and
gitignored --- it is a build artifact of `CLAUDE.md`, not a second source of
truth an agent could drift.
"""

from __future__ import annotations

import re
from pathlib import Path

import typer

# An import is a line that is *only* `@path` --- which is how the template
# writes them, and how the markdown formatter leaves them. Deliberately not
# matching inline `@foo`: prose in these files mentions handles and decorators,
# and inlining a file into the middle of a sentence is worse than missing it.
IMPORT_RE = re.compile(r"^@([^\s]+)\s*$")

MAX_DEPTH = 5

app = typer.Typer(
    add_completion=False,
    help="Render the agent's prompt files for the active runner.",
    no_args_is_help=True,
)


@app.callback()
def _main() -> None:
    """Force multi-command mode so `slop-prompt agents-md` works as expected."""


def expand_imports(
    text: str,
    read_file,
    seen: frozenset[str] = frozenset(),
    _depth: int = 0,
) -> str:
    """Replace `@path` lines in `text` with the contents of those files.

    `read_file` maps a path string to its contents, or to None if it is
    unreadable. A missing import is dropped silently, matching Claude Code's own
    behaviour --- the agent should see the same prompt shape either way.

    `seen` is the import chain so far. Callers should seed it with the path of
    `text` itself, or a file that imports its own importer takes one extra lap
    before the guard notices.

    Cycles and runaway nesting are bounded: a file already on the chain is
    skipped, as is anything past `MAX_DEPTH`. Both leave the `@line` in place
    rather than deleting it, so a broken chain is visible in the output instead
    of being invisibly swallowed.
    """
    out: list[str] = []
    for line in text.splitlines():
        match = IMPORT_RE.match(line)
        if not match:
            out.append(line)
            continue

        path = match.group(1)
        if path in seen or _depth >= MAX_DEPTH:
            out.append(line)
            continue

        content = read_file(path)
        if content is None:
            continue

        out.append(expand_imports(content, read_file, seen | {path}, _depth + 1))
    return "\n".join(out)


def _reader(root: Path):
    def read_file(path: str) -> str | None:
        target = root / path
        try:
            return target.read_text()
        except OSError:
            return None

    return read_file


@app.command(name="agents-md")
def agents_md(
    root: str = typer.Option(".", "--root", help="Repo root holding CLAUDE.md"),
    source: str = typer.Option("CLAUDE.md", "--source"),
    dest: str = typer.Option("AGENTS.md", "--dest"),
):
    """Write AGENTS.md: CLAUDE.md with its `@` imports inlined.

    Fail-open by design --- `slop-tick` runs this ahead of a codex tick, and a
    tick with a stale AGENTS.md is far better than no tick at all.
    """
    base = Path(root)
    src = base / source
    if not src.exists():
        typer.echo(f"slop-prompt: no {source} at {base}, nothing to render", err=True)
        return

    rendered = expand_imports(src.read_text(), _reader(base), frozenset({source}))
    header = (
        f"<!-- Generated from {source} by `slop-prompt agents-md`. "
        f"Do not edit: rewritten every codex tick. Edit {source} instead. -->\n\n"
    )
    (base / dest).write_text(header + rendered)
