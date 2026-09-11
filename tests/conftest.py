"""Shared unit-test fixtures."""

from __future__ import annotations

import pytest

REGISTRY = """
claude_version = "2.1.263"
default_provider = "gw"

[providers.gw]
base_url = "https://api.sprites.dev/v1/gateway/openrouter/conn1"
model = "z-ai/glm-5.3-flash@preset/slop-glm-flash"
auth = "connector"
context_window = 1000000

[providers.direct]
base_url = "https://openrouter.ai/api/"
model = "meta/muse-spark-1.3-contributor"
auth = "secret_env"
secret_env = "TEST_OPENROUTER_KEY"

[salons.one]
label = "One"
provider = "gw"

[salons.two]
label = "Two"
provider = "direct"

[souls.boden]
label = "Boden"
[souls.null]
label = "Make art."

[agents.lou]
handle = "lou.slopsalon.art"
github_repo = "ANUcybernetics/slop-salon-lou"
sprite_id = "lou"
salon = "one"
soul = "boden"
live = true

[agents.mina]
handle = "mina.slopsalon.art"
github_repo = "ANUcybernetics/slop-salon-mina"
sprite_id = "mina"
salon = "one"
soul = "null"
live = true

[agents.gert]
handle = "gert.slopsalon.art"
github_repo = "ANUcybernetics/slop-salon-gert"
sprite_id = "gert"
salon = "two"
soul = "boden"
live = true

[agents.vita]
handle = "vita.slopsalon.art"
github_repo = "ANUcybernetics/slop-salon-vita"
sprite_id = ""
salon = "two"
soul = "null"
live = false
"""

SECRETS = """
[agents.lou]
bsky_password = "lou-pw"
[agents.mina]
bsky_password = "mina-pw"
[agents.gert]
bsky_password = "gert-pw"
[agents.vita]
bsky_password = "vita-pw"
"""


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """Keep wake state (wedge counters, the last-wake stamp) out of the real
    ~/.local/state: on the admin box that file is live operational state."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg_state"))


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """A two-salon registry with secrets and templates, as the cwd."""
    (tmp_path / "slop_salon.toml").write_text(REGISTRY)
    (tmp_path / "secrets.toml").write_text(SECRETS)
    (tmp_path / "templates" / "notes").mkdir(parents=True)
    (tmp_path / "templates" / "CLAUDE.md").write_text(
        "# {{name}}\n\n{{handle}}; salon: {{siblings_prose}}\n\n"
        "@SOUL.md\n\n@MEMORY.md\n\n@notes/now.md\n"
    )
    (tmp_path / "templates" / "MEMORY.md").write_text("# {{name}}\n\n{{siblings_list}}\n")
    (tmp_path / "templates" / "notes" / "now.md").write_text("# now\n")
    (tmp_path / "templates" / "slop-tick").write_text("#!/bin/bash\n")
    (tmp_path / "souls").mkdir()
    (tmp_path / "souls" / "boden.md").write_text("# Boden\n")
    (tmp_path / "souls" / "null.md").write_text("Make art.\n")
    monkeypatch.setenv("SLOP_GH_TOKEN", "ghp_test")
    monkeypatch.setenv("SLOP_REPLICATE_API_TOKEN", "r8_test")
    monkeypatch.setenv("TEST_OPENROUTER_KEY", "sk-or-test")
    monkeypatch.setenv("SPRITES_API_TOKEN", "sprites-test")
    monkeypatch.chdir(tmp_path)
    return tmp_path / "slop_salon.toml"
