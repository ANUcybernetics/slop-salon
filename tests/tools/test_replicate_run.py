"""Tests for replicate-run."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture
def replicate_env(monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "test-token")


def test_text_output_prints_to_stdout(replicate_env):
    with patch("slop_salon.tools.replicate_run.replicate") as mock_replicate:
        mock_replicate.run.return_value = "a poem about light"

        from slop_salon.tools.replicate_run import app

        result = runner.invoke(app, ["meta/llama-3:abc", "--input", "prompt=write a poem"])

        assert result.exit_code == 0, result.output
        assert "a poem about light" in result.output


def test_image_output_downloads_to_assets(replicate_env, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fake_url = "https://replicate.delivery/pbxt/result.png"

    with (
        patch("slop_salon.tools.replicate_run.replicate") as mock_replicate,
        patch("slop_salon.tools.replicate_run.httpx") as mock_httpx,
    ):
        mock_replicate.run.return_value = [fake_url]
        mock_resp = MagicMock(content=b"\x89PNG\r\n\x1a\nfake")
        mock_resp.raise_for_status = MagicMock()
        mock_httpx.get.return_value = mock_resp

        from slop_salon.tools.replicate_run import app

        result = runner.invoke(app, ["stability/sdxl:v1", "--input", "prompt=cat"])

        assert result.exit_code == 0, result.output
        # Should have downloaded to ./assets/
        assets = tmp_path / "assets"
        assert assets.exists()
        downloaded = list(assets.iterdir())
        assert len(downloaded) == 1
        # The local path should be printed
        assert str(downloaded[0]) in result.output


def test_requires_token(monkeypatch):
    monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)

    from slop_salon.tools.replicate_run import app

    result = runner.invoke(app, ["x/y:z", "--input", "k=v"])

    assert result.exit_code != 0
    assert "REPLICATE_API_TOKEN" in (result.output + (result.stderr or ""))
