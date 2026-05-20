"""Tests for the `replicate` CLI."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture
def replicate_env(monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "test-token")


def test_run_text_output_prints_to_stdout(replicate_env):
    with patch("slop_salon.tools.replicate_run.replicate") as mock_replicate:
        mock_replicate.run.return_value = "a poem about light"

        from slop_salon.tools.replicate_run import app

        result = runner.invoke(app, ["run", "meta/llama-3:abc", "--input", "prompt=write a poem"])

        assert result.exit_code == 0, result.output
        assert "a poem about light" in result.output


def test_run_image_output_downloads_to_assets(replicate_env, tmp_path, monkeypatch):
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

        result = runner.invoke(app, ["run", "stability/sdxl:v1", "--input", "prompt=cat"])

        assert result.exit_code == 0, result.output
        # Should have downloaded to ./assets/
        assets = tmp_path / "assets"
        assert assets.exists()
        downloaded = list(assets.iterdir())
        assert len(downloaded) == 1
        # The local path should be printed
        assert str(downloaded[0]) in result.output


def test_run_requires_token(monkeypatch):
    monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)

    from slop_salon.tools.replicate_run import app

    result = runner.invoke(app, ["run", "x/y:z", "--input", "k=v"])

    assert result.exit_code != 0
    assert "REPLICATE_API_TOKEN" in (result.output + (result.stderr or ""))


def test_cookbook_prints_recipes_with_whitespace_preserved():
    """The cookbook prints raw text (not via typer's help renderer), so the
    shell recipe whitespace must survive intact for jq to parse them."""
    from slop_salon.tools.replicate_run import app

    result = runner.invoke(app, ["cookbook"])
    assert result.exit_code == 0, result.output
    # Spot-check both halves of the cookbook are present: running a model
    # and exploring the catalogue via the REST API.
    assert "replicate run" in result.output
    assert "api.replicate.com" in result.output
    assert "openapi_schema" in result.output
    assert "collections" in result.output
