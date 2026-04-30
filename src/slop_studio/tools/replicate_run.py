"""replicate-run: run any Replicate model from the command line.

Text outputs print to stdout. Media outputs (image/audio/video URLs)
download to ./assets/ by default; the local file paths print to stdout.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx
import replicate
import typer

app = typer.Typer(add_completion=False, help="Run a Replicate model.")


def _parse_input(items: list[str]) -> dict[str, object]:
    """Parse `key=value` strings into a dict. Numeric values are coerced."""
    result: dict[str, object] = {}
    for item in items:
        if "=" not in item:
            typer.echo(f"error: --input must be key=value, got {item!r}", err=True)
            raise typer.Exit(code=1)
        key, value = item.split("=", 1)
        if re.fullmatch(r"-?\d+", value):
            result[key] = int(value)
        elif re.fullmatch(r"-?\d*\.\d+", value):
            result[key] = float(value)
        else:
            result[key] = value
    return result


def _is_url(value) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"}


def _filename_from_url(url: str, idx: int) -> str:
    name = Path(urlparse(url).path).name
    return name or f"output-{idx}"


@app.command()
def run(
    model: str = typer.Argument(..., help="owner/model:version"),
    input: list[str] = typer.Option([], "--input", help="Model input as key=value (repeatable)"),
    output: Path = typer.Option(Path("assets"), "--output", help="Directory for downloaded media"),
):
    """Run a Replicate model with --input k=v ... and download any media."""
    if not os.environ.get("REPLICATE_API_TOKEN"):
        typer.echo("error: REPLICATE_API_TOKEN env var is required", err=True)
        raise typer.Exit(code=1)

    inputs = _parse_input(input)
    result = replicate.run(model, input=inputs)

    items = result if isinstance(result, list) else [result]
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    for idx, item in enumerate(items):
        if _is_url(item):
            response = httpx.get(item)
            response.raise_for_status()
            target = output / _filename_from_url(item, idx)
            target.write_bytes(response.content)
            typer.echo(str(target))
        else:
            typer.echo(item if isinstance(item, str) else str(item))
