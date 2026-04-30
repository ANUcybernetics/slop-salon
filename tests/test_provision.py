"""Tests for slop_studio.provision."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_resolve_secrets_runs_fnox_and_returns_env():
    from slop_studio.provision import resolve_secrets_via_fnox

    fake_env_output = (
        "BSKY_HANDLE=boden.slopsalon.art\nBSKY_PASSWORD=topsecret\nANTHROPIC_API_KEY=sk-ant-xxx\n"
    )

    with patch("slop_studio.provision.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=fake_env_output, returncode=0)

        env = resolve_secrets_via_fnox("boden")

    assert env["BSKY_HANDLE"] == "boden.slopsalon.art"
    assert env["BSKY_PASSWORD"] == "topsecret"
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-xxx"

    # Verify it called fnox correctly
    args = mock_run.call_args[0][0]
    assert args[0:3] == ["fnox", "exec", "--profile"]
    assert args[3] == "boden"


def test_resolve_secrets_raises_on_fnox_failure():
    from slop_studio.provision import resolve_secrets_via_fnox

    with patch("slop_studio.provision.subprocess.run") as mock_run:
        mock_run.side_effect = Exception("fnox: profile not found")

        with pytest.raises(Exception, match="fnox"):
            resolve_secrets_via_fnox("nonexistent")
