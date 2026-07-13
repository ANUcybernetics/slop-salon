"""Push a single file into a GitHub repo via the Contents API.

Clone-free by design. The agent repos run to ~1 GB of committed assets, which
makes even a shallow `gh repo clone` disconnect mid-fetch --- so the admin-side
push helpers (`ops/push-template.py`, `ops/push-rite.py`) write one file at a
time through the REST Contents API instead, which never touches the blobs.
"""

from __future__ import annotations

import base64
import json
import subprocess


def put_file(repo: str, path: str, content: str, message: str, env: dict[str, str]) -> str:
    """Create-or-update one file in ``repo`` on its default branch.

    GETs the current blob for its SHA (required to update, and to skip an
    identical write); PUTs ``content`` with ``message``. Returns one of
    ``"created"`` / ``"updated"`` / ``"unchanged"``. Raises on a failed PUT.
    """
    show = subprocess.run(
        ["gh", "api", f"repos/{repo}/contents/{path}"],
        capture_output=True,
        text=True,
        env=env,
    )
    sha: str | None = None
    if show.returncode == 0:
        info = json.loads(show.stdout)
        if base64.b64decode(info.get("content", "")).decode() == content:
            return "unchanged"
        sha = info.get("sha")
    args = [
        "gh",
        "api",
        "--method",
        "PUT",
        f"repos/{repo}/contents/{path}",
        "-f",
        f"message={message}",
        "-f",
        f"content={base64.b64encode(content.encode()).decode()}",
    ]
    if sha is not None:
        args += ["-f", f"sha={sha}"]
    subprocess.run(args, check=True, capture_output=True, text=True, env=env)
    return "updated" if sha is not None else "created"
