"""The Codex login the luna salon ticks on, kept fresh on the admin box.

Codex revokes a refresh token once it is used, so one login cannot be shared by
two machines that both refresh it: whichever refreshes second is logged out.
The admin box therefore holds the only refresh token. Before shipping the login
it forces a refresh through `codex app-server` whenever the access token would
not outlast a wake, and each sprite gets a copy with the refresh token blanked:
its access token lasts the tick, and nothing a sprite does can spend the admin
box's login.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import subprocess
import threading
from pathlib import Path

# Longer than the wake unit's 12h cap, since every tick in a wake ships the
# login read at its start, plus codex's own 5-minute refresh window. An access
# token lasts 10 days, so this forces a refresh roughly every 9.
REFRESH_MARGIN = dt.timedelta(days=1)
REFRESH_TIMEOUT_S = 90

_RELOGIN = "run `codex login --device-auth` on the admin box"


def access_token_expiry(auth: dict) -> dt.datetime:
    """When the login's access token expires, from its JWT `exp` claim."""
    token = auth.get("tokens", {}).get("access_token", "")
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return dt.datetime.fromtimestamp(claims["exp"], dt.UTC)
    except (IndexError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(f"the Codex login has no readable access token; {_RELOGIN}") from exc


def force_refresh(codex: str = "codex") -> None:
    """Have codex refresh its login and rewrite the file, without a model call.

    `account/read` with `refreshToken` is the app-server's request for exactly
    this. It answers even when the refresh fails, so the caller checks the
    file afterwards rather than trusting the reply.
    """
    requests = [
        {
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {"name": "slop", "version": "0"}},
        },
        {"method": "initialized"},
        {"id": 2, "method": "account/read", "params": {"refreshToken": True}},
    ]
    proc = subprocess.Popen(
        [codex, "app-server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    assert proc.stdin and proc.stdout
    timer = threading.Timer(REFRESH_TIMEOUT_S, proc.kill)
    timer.start()
    try:
        for request in requests:
            proc.stdin.write(json.dumps({"jsonrpc": "2.0", **request}) + "\n")
        proc.stdin.flush()
        for line in proc.stdout:
            message = json.loads(line)
            if message.get("id") == 2:
                if "error" in message:
                    raise RuntimeError(f"codex app-server refused account/read: {message['error']}")
                return
        raise RuntimeError(f"codex app-server exited without answering account/read; {_RELOGIN}")
    finally:
        timer.cancel()
        proc.kill()
        proc.wait()


def ensure_fresh(path: Path, *, now: dt.datetime | None = None, codex: str = "codex") -> bytes:
    """The login file's bytes, refreshed first if it would expire within
    `REFRESH_MARGIN`. Raises if it still would after the refresh."""
    now = now or dt.datetime.now(dt.UTC)
    if access_token_expiry(json.loads(path.read_bytes())) - now >= REFRESH_MARGIN:
        return path.read_bytes()
    force_refresh(codex)
    raw = path.read_bytes()
    expiry = access_token_expiry(json.loads(raw))
    if expiry - now < REFRESH_MARGIN:
        raise RuntimeError(
            f"the Codex login expires {expiry:%Y-%m-%d %H:%M}Z and would not refresh; {_RELOGIN}"
        )
    return raw


def sprite_copy(raw: bytes) -> bytes:
    """The login as a sprite gets it: the refresh token blanked."""
    auth = json.loads(raw)
    auth["tokens"]["refresh_token"] = ""
    return json.dumps(auth).encode()
