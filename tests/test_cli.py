"""Tests for the `slop` admin CLI (the parts not covered by their own modules)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from slop_salon.cli import _render_transcripts, app
from slop_salon.sprites import ExecResult
from slop_salon.tick import SESSION_MARKER

runner = CliRunner()


def test_status_lists_agents(registry):
    with patch("slop_salon.cli.SpritesClient") as mock_class:
        instance = MagicMock()
        instance.get_status.side_effect = lambda sid: {
            "lou": "warm",
            "mina": "cold",
            "gert": "cold",
        }[sid]
        mock_class.return_value = instance
        result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.output
    assert "lou        lou.slopsalon.art          one         boden    warm" in result.output
    assert "vita" in result.output and "not provisioned" in result.output


def test_talk_runs_slop_tick_with_the_tick_env(registry):
    with patch("slop_salon.cli.SpritesClient") as mock_class:
        instance = MagicMock()
        instance.exec.return_value = ExecResult(
            stdout=f"{SESSION_MARKER}\ndone", stderr="", exit_code=0
        )
        mock_class.return_value = instance
        result = runner.invoke(app, ["talk", "lou", "say hi"])
    assert result.exit_code == 0, result.output
    sprite_id, command = instance.exec.call_args.args
    env = instance.exec.call_args.kwargs["env"]
    assert sprite_id == "lou"
    assert command == ["bash", "-lc", f"echo '{SESSION_MARKER}'; slop-tick 'say hi'"]
    assert env["AGENT_NAME"] == "lou" and env["ANTHROPIC_MODEL"].startswith("z-ai/")
    assert SESSION_MARKER not in result.output and "done" in result.output


def test_wake_only_ticks_the_named_agents_and_stamps(registry, tmp_path):
    with patch("slop_salon.cli.SpritesClient") as mock_class:
        instance = MagicMock()
        instance.exec.return_value = ExecResult(stdout=SESSION_MARKER, stderr="", exit_code=0)
        mock_class.return_value = instance
        result = runner.invoke(app, ["wake", "--only", "mina"])
    assert result.exit_code == 0, result.output
    assert [c.args[0] for c in instance.exec.call_args_list] == ["mina"]
    stamp = json.loads((tmp_path / "xdg_state" / "slop" / "last-wake.json").read_text())
    assert stamp["statuses"] == {"mina": "ok"}


def test_wake_is_red_when_any_agent_fails(registry):
    with patch("slop_salon.cli.SpritesClient") as mock_class:
        instance = MagicMock()
        instance.exec.side_effect = lambda sid, cmd, env=None: (
            ExecResult(stdout=SESSION_MARKER, stderr="fatal: conflict", exit_code=128)
            if sid == "gert"
            else ExecResult(stdout=SESSION_MARKER, stderr="", exit_code=0)
        )
        mock_class.return_value = instance
        result = runner.invoke(app, ["wake"])
    assert result.exit_code == 1
    assert "gert" in result.output and "fail(128)" in result.output


def test_logs_renders_transcript_from_sprite(registry):
    transcript = "\n".join(
        [
            "<<<SLOPLOG abc12345-session.jsonl 2026-06-02T10:02:21Z>>>",
            json.dumps(
                {
                    "type": "user",
                    "timestamp": "2026-06-02T10:02:21.478Z",
                    "message": {"content": "tick"},
                }
            ),
            json.dumps(
                {
                    "type": "assistant",
                    "timestamp": "2026-06-02T10:02:25.000Z",
                    "message": {
                        "content": [
                            {"type": "tool_use", "name": "Bash", "input": {"command": "ls notes"}},
                            {"type": "text", "text": "Reading the timeline."},
                        ]
                    },
                }
            ),
        ]
    )
    with patch("slop_salon.cli.SpritesClient") as mock_class:
        instance = MagicMock()
        instance.exec.return_value = ExecResult(stdout=transcript, stderr="", exit_code=0)
        mock_class.return_value = instance
        result = runner.invoke(app, ["logs", "lou"])
    assert result.exit_code == 0, result.output
    assert "-- tick abc12345 · 2026-06-02T10:02:21Z --" in result.output
    assert "10:02:21  user       tick" in result.output
    assert '-> Bash({"command":"ls notes"})' in result.output
    assert "assistant  Reading the timeline." in result.output


def test_render_transcripts_is_pure():
    assert _render_transcripts("") == ""
    assert _render_transcripts("<<<SLOPLOG a.jsonl>>>\nnot json\n") == "-- tick a --"


def test_policy_applies_the_allowlist_to_every_live_sprite(registry):
    with patch("slop_salon.cli.SpritesClient") as mock_class:
        instance = MagicMock()
        mock_class.return_value = instance
        result = runner.invoke(app, ["policy"])
    assert result.exit_code == 0, result.output
    assert [c.args[0] for c in instance.set_network_policy.call_args_list] == [
        "lou",
        "mina",
        "gert",
    ]


def test_new_invokes_provisioning(registry):
    with patch("slop_salon.cli.provision_agent") as prov:
        result = runner.invoke(app, ["new", "vita", "--yes-dns"])
    assert result.exit_code == 0, result.output
    prov.assert_called_once_with("vita", config_path="slop_salon.toml", skip_dns_confirm=True)


def test_drift_reports_clean_and_drift(registry):
    with patch("slop_salon.cli._fetch_live_files") as fetch:
        fetch.return_value = {"SOUL.md": "# Boden\n", "CLAUDE.md": "# lou\n\nrewritten by lou\n"}
        result = runner.invoke(app, ["drift", "lou", "-f", "SOUL.md", "-f", "CLAUDE.md"])
    assert result.exit_code == 0, result.output
    assert "SOUL.md         clean" in result.output
    assert "CLAUDE.md       drift (+1/-" in result.output
