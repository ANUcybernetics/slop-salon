"""Provisioning: templates, the sprite bootstrap, and the real shipped templates."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slop_salon import provision as prov
from slop_salon.config import load_config
from slop_salon.provision import (
    EGRESS_RULES,
    bootstrap_sprite,
    bootstrap_steps,
    build_template_files,
    provision_agent,
    write_files,
)
from slop_salon.sprites import ExecResult

ROOT = Path(__file__).resolve().parent.parent


def test_build_template_files_interpolates_and_adds_the_soul(registry):
    config = load_config(registry)
    files = build_template_files(config, config.agents["lou"])
    assert files["SOUL.md"] == "# Boden\n"
    assert files["CLAUDE.md"].startswith(
        "# lou\n\nlou.slopsalon.art; salon: mina (`mina.slopsalon.art`)"
    )
    assert files["MEMORY.md"] == "# lou\n\n- mina: `mina.slopsalon.art`\n"
    assert files["notes/now.md"] == "# now\n"
    assert build_template_files(config, config.agents["mina"])["SOUL.md"] == "Make art.\n"


def test_an_agent_without_a_soul_cannot_be_rendered(registry):
    config = load_config(registry)
    config.agents["lou"].soul = ""
    with pytest.raises(ValueError, match="no soul"):
        build_template_files(config, config.agents["lou"])


def test_write_files_makes_shebang_files_executable(tmp_path):
    write_files(tmp_path, {"slop-tick": "#!/bin/bash\n", "notes/now.md": "# now\n"})
    assert (tmp_path / "slop-tick").stat().st_mode & 0o111
    assert not (tmp_path / "notes" / "now.md").stat().st_mode & 0o111


def test_bootstrap_is_clone_then_setup_then_pin():
    steps = bootstrap_steps("lou", "ANUcybernetics/slop-salon-lou", "2.1.263")
    assert [label for label, _ in steps] == ["clone repo", "run setup.sh", "pin claude 2.1.263"]
    clone, setup, pin = (cmd for _, cmd in steps)
    # Public HTTPS, no token in the URL: pushes get theirs from the tick env.
    assert (
        clone
        == "git clone --quiet https://github.com/ANUcybernetics/slop-salon-lou.git ~/slop-salon-lou"
    )
    assert setup == "cd ~/slop-salon-lou && ./setup.sh"
    assert pin == "claude install 2.1.263 --force"
    assert len(bootstrap_steps("lou", "r", "")) == 2


def test_bootstrap_sprite_labels_fences_then_runs_the_steps(registry):
    config = load_config(registry)
    sprites = MagicMock()
    sprites.exec.return_value = ExecResult(stdout="", stderr="", exit_code=0)
    bootstrap_sprite(sprites, config, config.agents["lou"])
    sprites.set_labels.assert_called_once_with("lou", ["slop", "salon=one"])
    sprites.set_network_policy.assert_called_once_with("lou", EGRESS_RULES)
    assert [c.args[1][2] for c in sprites.exec.call_args_list] == [
        cmd for _, cmd in bootstrap_steps("lou", "ANUcybernetics/slop-salon-lou", "2.1.263")
    ]


def test_bootstrap_sprite_raises_on_a_failed_step(registry):
    config = load_config(registry)
    sprites = MagicMock()
    sprites.exec.return_value = ExecResult(stdout="", stderr="apt broke", exit_code=100)
    with pytest.raises(RuntimeError, match=r"clone repo failed.*apt broke"):
        bootstrap_sprite(sprites, config, config.agents["lou"])


def test_egress_rules_include_platform_defaults_and_the_tools_hosts():
    assert EGRESS_RULES[0] == {"include": "defaults"}
    domains = {r["domain"] for r in EGRESS_RULES[1:]}
    for needed in (
        "api.sprites.dev",
        "bsky.social",
        "*.bsky.network",
        "api.replicate.com",
        "*.replicate.delivery",
    ):
        assert needed in domains
    assert all(r.get("action") == "allow" for r in EGRESS_RULES[1:])


def test_provision_creates_pushes_then_builds_the_sprite(registry):
    config = load_config(registry)
    sprites = MagicMock()
    sprites.create_sprite.return_value = "vita"
    sprites.exec.return_value = ExecResult(stdout="", stderr="", exit_code=0)
    calls: list[str] = []
    with (
        patch.object(prov, "SpritesClient", return_value=sprites),
        patch.object(prov.subprocess, "run") as run,
        patch.object(prov, "push_initial_commit", side_effect=lambda *a: calls.append("push")),
    ):
        run.return_value = MagicMock(returncode=1)  # repo does not exist yet
        provision_agent("vita", config_path=registry, skip_dns_confirm=True)
    assert calls == ["push"]
    assert run.call_args_list[1].args[0][:3] == ["gh", "repo", "create"]
    sprites.create_sprite.assert_called_once_with("vita", labels=["slop", "salon=two"])
    sprites.set_network_policy.assert_called_once()
    assert load_config(registry).agents["vita"].sprite_id == "vita"
    del config


def test_provision_fails_before_creating_anything_when_a_secret_is_missing(registry, monkeypatch):
    monkeypatch.delenv("SLOP_GH_TOKEN")
    with (
        patch.object(prov, "SpritesClient") as sprites,
        patch.object(prov.subprocess, "run") as run,
        pytest.raises(RuntimeError, match="SLOP_GH_TOKEN"),
    ):
        provision_agent("vita", config_path=registry, skip_dns_confirm=True)
    sprites.assert_not_called()
    run.assert_not_called()


# --- The shipped templates ---


def _shipped() -> dict[str, str]:
    config = load_config(ROOT / "slop_salon.toml")
    return build_template_files(config, config.agents["lou"], ROOT / "templates", ROOT / "souls")


def test_every_claude_md_import_names_a_file_we_ship():
    """A missing `@` import is skipped silently by Claude Code."""
    files = _shipped()
    imports = re.findall(r"^@(\S+)$", files["CLAUDE.md"], re.MULTILINE)
    assert imports == ["SOUL.md", "MEMORY.md", "notes/now.md"]
    for path in imports:
        assert path in files, f"CLAUDE.md imports {path}, which is not shipped"


def test_claude_md_is_short_and_carries_the_numbered_routine():
    text = _shipped()["CLAUDE.md"]
    assert len(text.splitlines()) <= 110
    steps = re.findall(r"^\d+\. ", text, re.MULTILINE)
    assert 6 <= len(steps) <= 10
    assert "TZ=Australia/Canberra date +%H" in text
    assert "wc -c MEMORY.md" in text


def test_memory_stub_starts_well_under_its_cap():
    assert len(_shipped()["MEMORY.md"].encode()) < 2000


def test_setup_and_tick_are_executable_and_store_no_secret():
    files = _shipped()
    for name in ("setup.sh", "slop-tick"):
        assert files[name].startswith("#!")
    assert "GH_TOKEN:?" in files["setup.sh"]  # read from the env at push time
    assert "ghp_" not in files["setup.sh"]
    assert ".slop-env" not in files["slop-tick"]
