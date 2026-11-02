"""The admin box keeps the only Codex refresh token and refreshes it before a
wake could outlive the access token."""

from __future__ import annotations

import base64
import datetime as dt
import json
import os

import pytest

from slop_salon.codex_login import access_token_expiry
from slop_salon.config import load_config
from slop_salon.tick import tick_env
from tests.conftest import codex_login_json, use_provider

FAKE_CODEX = """\
#!/usr/bin/env python3
# Stands in for `codex app-server`: logs each call and, on account/read with
# refreshToken, rewrites the login unless FAKE_CODEX_STUCK is set.
import json, os, sys
def reply(msg, result):
    print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)
open(os.environ["FAKE_CODEX_LOG"], "a").write(" ".join(sys.argv[1:]) + "\\n")
for line in sys.stdin:
    msg = json.loads(line)
    if msg.get("method") == "account/read":
        if msg["params"].get("refreshToken") and not os.environ.get("FAKE_CODEX_STUCK"):
            open(os.environ["SLOP_CODEX_AUTH_PATH"], "w").write(os.environ["FAKE_CODEX_REFRESHED"])
        reply(msg, {"account": None})
    elif "id" in msg:
        reply(msg, {})
"""


@pytest.fixture
def luna(registry, tmp_path, monkeypatch):
    """gert on the codex salon, with a fake codex first on PATH."""
    use_provider(registry, "two", "luna")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "codex"
    fake.write_text(FAKE_CODEX)
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    log = tmp_path / "codex-calls.log"
    monkeypatch.setenv("FAKE_CODEX_LOG", str(log))
    now = dt.datetime.now(dt.UTC)
    monkeypatch.setenv(
        "FAKE_CODEX_REFRESHED", codex_login_json(now + dt.timedelta(days=10), access="new")
    )
    config = load_config(registry)
    return config, config.agents["gert"], tmp_path / "codex-auth.json", log


def _shipped(env):
    return json.loads(base64.b64decode(env["SLOP_CODEX_AUTH"]))


def test_a_login_with_days_left_ships_without_refreshing(luna):
    config, gert, _, log = luna
    env = tick_env(config, gert)
    assert not log.exists()
    assert _shipped(env)["tokens"]["refresh_token"] == ""


def test_a_login_about_to_expire_is_refreshed_before_it_ships(luna):
    config, gert, auth_path, log = luna
    auth_path.write_text(codex_login_json(dt.datetime.now(dt.UTC) + dt.timedelta(hours=6)))
    env = tick_env(config, gert)
    assert log.read_text() == "app-server\n"
    tokens = _shipped(env)["tokens"]
    assert tokens["access_token"].endswith(".new")
    assert tokens["refresh_token"] == ""
    # The admin box keeps its refresh token.
    assert json.loads(auth_path.read_text())["tokens"]["refresh_token"] == "rt-admin"


def test_a_refresh_that_does_not_take_fails_the_wake_naming_the_fix(luna, monkeypatch):
    config, gert, auth_path, _ = luna
    auth_path.write_text(codex_login_json(dt.datetime.now(dt.UTC) + dt.timedelta(hours=6)))
    monkeypatch.setenv("FAKE_CODEX_STUCK", "1")
    with pytest.raises(RuntimeError, match="codex login --device-auth"):
        tick_env(config, gert)


def test_an_unreadable_access_token_is_named():
    with pytest.raises(RuntimeError, match="no readable access token"):
        access_token_expiry({"tokens": {"access_token": "not-a-jwt"}})


def test_expiry_is_read_from_the_access_tokens_exp_claim():
    when = dt.datetime(2026, 11, 12, 3, 0, tzinfo=dt.UTC)
    assert access_token_expiry(json.loads(codex_login_json(when))) == when
