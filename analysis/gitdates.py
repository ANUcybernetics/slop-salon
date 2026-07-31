"""Author-date commit selection for the weekly pilots.

Git's `log --since/--until` and `rev-list --before` filter on the COMMITTER
date, which is not when the agent wrote anything --- it is when the object was
last written. Any history rewrite restamps it. lou's 16-day push failure
(2026-06-24 to 07-10, task-8) was recovered with filter-branch, which preserved
author dates but reset every committer date in that window to 2026-07-09. Under
committer-date bucketing lou's writing for those weeks vanishes from its own
weeks and lands as one 937k-character burst in the week of 2026-07-13 --- the
same week the image pilot dates the fleet's turn toward plotting, so the
artefact sits directly on top of the result.

Author date is the tick that wrote the note, survives rewriting, and is what
every weekly measure here means. Select on it.
"""

import subprocess
from datetime import date
from pathlib import Path


def _log(repo: Path, *args: str, stdin: str | None = None) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        input=stdin,
    ).stdout


def commits_in_range(repo: Path, since: date, until: date) -> list[str]:
    """SHAs whose AUTHOR date falls in [since, until), newest first."""
    out = _log(repo, "log", "--format=%H %ad", "--date=short", "HEAD")
    picked = []
    for line in out.splitlines():
        sha, _, day = line.partition(" ")
        if since.isoformat() <= day < until.isoformat():
            picked.append(sha)
    return picked


def patch_for(repo: Path, shas: list[str], pathspec: str = "*.md") -> str:
    """Combined patch for `shas`, each against its first parent.

    Fed on stdin so the command line stays bounded --- a busy agent-week runs
    to hundreds of commits.
    """
    if not shas:
        return ""
    return _log(
        repo,
        "log",
        "--stdin",
        "--no-walk",
        "-p",
        "--diff-filter=AM",
        "--",
        pathspec,
        stdin="\n".join(shas) + "\n",
    )


def rev_at(repo: Path, day: date) -> str | None:
    """Newest commit whose AUTHOR date is on or before `day`."""
    out = _log(repo, "log", "--format=%H %ad", "--date=short", "HEAD")
    for line in out.splitlines():
        sha, _, d = line.partition(" ")
        if d <= day.isoformat():
            return sha
    return None
