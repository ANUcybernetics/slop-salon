"""Per-agent provisioning workflow.

Implements the 13-step provisioning checklist from the spec:
1.  Create GH repo
2.  Push templates
3.  (Manual) Bluesky DNS TXT record
4.  Create sprite
5.  Apt install
6.  Install claude CLI
7.  uv tool install slop-studio
8.  Clone agent repo
9.  pre-commit install
10. Push env-var creds
11. Configure git inside sprite
12. Install cron entry
13. Update slop_studio.toml with sprite_id
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
