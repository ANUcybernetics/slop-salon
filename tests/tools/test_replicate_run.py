"""Tests for the `replicate` CLI."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from replicate.helpers import FileOutput
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


PNG = b"\x89PNG\r\n\x1a\nfake"
URL = "https://replicate.delivery/pbxt/result.png"


def _response(content: bytes, content_type: str) -> httpx.Response:
    """A real Response --- a MagicMock would satisfy any guard we write."""
    return httpx.Response(
        200,
        content=content,
        headers={"content-type": content_type},
        request=httpx.Request("GET", URL),
    )


def _file_output(url: str) -> FileOutput:
    """What `replicate.run` actually returns: not a str."""
    out = FileOutput.__new__(FileOutput)
    out.url = url
    return out


def test_run_image_output_downloads_to_assets(replicate_env, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with (
        patch("slop_salon.tools.replicate_run.replicate") as mock_replicate,
        patch("slop_salon.tools.replicate_run.httpx.get") as mock_get,
    ):
        mock_replicate.run.return_value = [URL]
        mock_get.return_value = _response(PNG, "image/png")

        from slop_salon.tools.replicate_run import app

        result = runner.invoke(app, ["run", "stability/sdxl:v1", "--input", "prompt=cat"])

        assert result.exit_code == 0, result.output
        downloaded = list((tmp_path / "assets").iterdir())
        assert len(downloaded) == 1
        assert downloaded[0].read_bytes() == PNG
        assert str(downloaded[0]) in result.output


def test_run_downloads_a_fileoutput_not_just_a_str(replicate_env, tmp_path, monkeypatch):
    """Regression: replicate.run returns FileOutput, which is not a str.

    An `isinstance(item, str)` gate skipped every download silently, so the tool
    printed the URL and agents fetched it with `curl -s -L` --- which, lacking
    -f, saved 404 bodies as .webp and killed whichever tick later read one.
    """
    monkeypatch.chdir(tmp_path)

    with (
        patch("slop_salon.tools.replicate_run.replicate") as mock_replicate,
        patch("slop_salon.tools.replicate_run.httpx.get") as mock_get,
    ):
        mock_replicate.run.return_value = [_file_output(URL)]
        mock_get.return_value = _response(PNG, "image/png")

        from slop_salon.tools.replicate_run import app

        result = runner.invoke(app, ["run", "stability/sdxl:v1", "--input", "prompt=cat"])

        assert result.exit_code == 0, result.output
        assert mock_get.called, "FileOutput was never downloaded"
        downloaded = list((tmp_path / "assets").iterdir())
        assert len(downloaded) == 1
        assert downloaded[0].read_bytes() == PNG


def test_run_refuses_to_save_an_error_body_as_media(replicate_env, tmp_path, monkeypatch):
    """The exact shape found across all six repos: a 404 body named .webp."""
    monkeypatch.chdir(tmp_path)

    with (
        patch("slop_salon.tools.replicate_run.replicate") as mock_replicate,
        patch("slop_salon.tools.replicate_run.httpx.get") as mock_get,
    ):
        mock_replicate.run.return_value = [_file_output(URL)]
        mock_get.return_value = _response(
            b'{"detail": "requested file not found"}', "application/json"
        )

        from slop_salon.tools.replicate_run import app

        result = runner.invoke(app, ["run", "stability/sdxl:v1", "--input", "prompt=cat"])

        assert result.exit_code == 1
        assert "refusing to save" in (result.output + (result.stderr or ""))
        assert not (tmp_path / "assets").exists() or not list((tmp_path / "assets").iterdir())


def test_run_refuses_an_output_that_names_a_file(replicate_env, tmp_path, monkeypatch):
    """`--output assets/x.webp` used to mkdir a *directory* called x.webp."""
    monkeypatch.chdir(tmp_path)

    from slop_salon.tools.replicate_run import app

    result = runner.invoke(
        app,
        ["run", "stability/sdxl:v1", "--input", "prompt=cat", "--output", "assets/x.webp"],
    )

    assert result.exit_code == 2
    assert "directory, not a file" in (result.output + (result.stderr or ""))
    assert not (tmp_path / "assets" / "x.webp").exists()


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
