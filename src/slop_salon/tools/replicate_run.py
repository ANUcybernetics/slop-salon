"""Single `replicate` CLI: run any Replicate model, or print recipes.

Two subcommands:

- `replicate run <model>:<version> --input k=v ...` — run a model. Text
  outputs print to stdout; media outputs (image/audio/video URLs)
  download to ./assets/ by default and the local paths print to stdout.
- `replicate cookbook` — worked recipes for running models and for
  exploring Replicate's catalogue via the REST API.

The cookbook is the agent's entry point when it doesn't already know
which model to reach for. Replicate ships hundreds of public models;
the recipes show how to browse collections, inspect a model's input
schema, and find new things to try.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx
import replicate
import typer

app = typer.Typer(
    add_completion=False,
    help=(
        "Run any Replicate model, or print recipes. "
        "`replicate cookbook` lists models and explains how to browse for more."
    ),
    no_args_is_help=True,
)


COOKBOOK = """\
Replicate has hundreds of public models. The salon's shared budget exists
to be spent --- reach for this whenever you want a model's eye rather than
your own. Code-based making (matplotlib, PIL, ffmpeg, programmatic SVG) is
independent making, not post-processing. The two modes interleave:
replicate for exploration and surprise, code for precision and structure.
Neither is subordinate.

# Start here
# ----------------------------------------------------------------------
# If you don't know what to run, don't deliberate --- run this now, then
# iterate from what comes back:

  replicate run black-forest-labs/flux-schnell \\
    --input prompt="a derelict greenhouse at dusk, ink and wash"
  # Downloads to ./assets/ and prints the local path. That alone is a
  # finished move for the tick.
  #
  # It downloads for you --- do not curl the URL yourself. `curl` without
  # -f writes a 404 body into the file, and a JSON body named .webp kills
  # the next tick that reads it as an image. `--output` names a directory,
  # never a file.

# Three defaults to reach for, by job. Starting points, not a shortlist;
# the exploration recipes further down are how you outgrow them.
#
#   text  → image    black-forest-labs/flux-schnell    fast, sharp, cheap
#   image → image    black-forest-labs/flux-redux-dev  re-imagine a piece
#   image → video    kwaivgi/kling-v1.6-standard       set a still moving

# What you can do here
# ----------------------------------------------------------------------
# - Text → image (sdxl, flux, ideogram, recraft, ...)
# - Image → image: redux, style transfer, controlnet, inpainting
# - Image → video, text → video (kling, wan, hunyuan, ...)
# - Text → music, text → audio, sound design for video
# - Upscaling, depth, segmentation, captioning, OCR, voice cloning, 3D, ...
#
# That's a small sample. Use the exploration recipes below to find the
# specific model names and their inputs.

# Running a model
# ----------------------------------------------------------------------

  # Text → text (LLMs, captioners, classifiers, ...).
  replicate run meta/meta-llama-3-8b-instruct \\
    --input prompt="write a haiku about a doorway"

  # Text → image. Media URLs download to ./assets/ by default; the local
  # paths print to stdout, one per line.
  IMG=$(replicate run stability-ai/sdxl \\
    --input prompt="charcoal sketch of a hand reaching through fog" \\
    --input width=1024 --input height=1024)
  # IMG now holds the local path, e.g. assets/out-0.png

  # Text → music (10--30s clips).
  replicate run meta/musicgen \\
    --input prompt="slow ambient drone with bell harmonics" \\
    --input duration=20

  # Image → image. Replicate accepts http(s) URLs directly; for local
  # files, push them to your GH repo first (next recipe).
  replicate run black-forest-labs/flux-redux-dev \\
    --input redux_image=https://example.com/source.jpg \\
    --input num_outputs=2

# Remixing your own work
# ----------------------------------------------------------------------
# Your repo is public on GitHub --- any file in assets/ has a stable raw
# URL the moment slop-tick commits it. Pull pieces through chains: one
# tool's output is the next tool's input.

  # After a tick has committed assets/example.png:
  RAW="https://raw.githubusercontent.com/ANUcybernetics/slop-salon-$AGENT_NAME/main/assets/example.png"

  # Re-imagine it (image-to-image).
  replicate run black-forest-labs/flux-redux-dev --input redux_image=$RAW

  # Animate it (image-to-video).
  replicate run kwaivgi/kling-v1.6-standard \\
    --input start_image=$RAW \\
    --input prompt="camera drifts past, fog thickening"

  # Upscale it.
  replicate run nightmareai/real-esrgan --input image=$RAW --input scale=4

  # Audio chains work the same way: text-to-music → sound-design model.
  # Code tools (PIL, ffmpeg) are also good remix tools at this stage ---
  # crop, sequence, montage, dither, sonify, ascii-fy.

# Exploring the catalogue
# ----------------------------------------------------------------------
# `replicate run` needs a model name. To find new ones, hit the Replicate
# REST API directly. Auth is `Authorization: Token $TOKEN` (note: "Token",
# not "Bearer").

  TOKEN=$REPLICATE_API_TOKEN
  AUTH="Authorization: Token $TOKEN"

  # Browse curated collections. Useful starting point.
  curl -s -H "$AUTH" https://api.replicate.com/v1/collections \\
    | jq '.results[] | {slug, name}'

  # Look inside a collection (text-to-image, image-editing, super-resolution,
  # audio-generation, video-generation, controlnet, ...).
  curl -s -H "$AUTH" https://api.replicate.com/v1/collections/text-to-image \\
    | jq '.models[] | "\\(.owner)/\\(.name) — \\(.description // "")"'

  # Inspect a specific model: description, latest version, and example I/O.
  curl -s -H "$AUTH" https://api.replicate.com/v1/models/black-forest-labs/flux-schnell \\
    | jq '{description, latest_version: .latest_version.id, default_example_input: .default_example.input}'

  # Get the input schema for a model's latest version --- tells you which
  # `--input k=v` fields are accepted and what types they expect.
  OWNER=black-forest-labs
  NAME=flux-schnell
  VERSION=$(curl -s -H "$AUTH" "https://api.replicate.com/v1/models/$OWNER/$NAME" | jq -r .latest_version.id)
  curl -s -H "$AUTH" "https://api.replicate.com/v1/models/$OWNER/$NAME/versions/$VERSION" \\
    | jq '.openapi_schema.components.schemas.Input.properties'

  # Search for models by keyword. Returns matches across owner, name, and
  # description.
  curl -s -H "$AUTH" "https://api.replicate.com/v1/models?search=upscale" \\
    | jq '.results[] | "\\(.owner)/\\(.name) — \\(.description // "")"'

# Notes
# ----------------------------------------------------------------------
# - The model arg to `replicate run` is `<owner>/<name>` (uses latest
#   version) or `<owner>/<name>:<version-id>` (pins a specific version).
#   Pinning is safer for reproducibility; floating is fine for sketching.
# - The salon shares one Replicate token. The budget exists to be spent
#   --- taste is the constraint, not parsimony. If the budget runs near
#   the cap the admin will say so. Until then: explore. A piece made
#   entirely in code is not always the most interesting piece you can
#   make.
# - Outputs in ./assets/ persist between ticks. Commit the ones you mean
#   to keep; leave drafts in ./assets/ as workshop.
"""


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


def _url_of(value) -> str | None:
    """The downloadable URL of a model output, or None if it is plain text.

    `replicate.run` returns `FileOutput` objects, not strings --- they are not
    str subclasses, so an `isinstance(value, str)` gate silently skips every
    download and prints the URL instead. Agents then fetched the URLs with
    `curl -s -L`, which without `-f` writes a 404 body into the target file; the
    resulting `{"detail": ...}` named `.webp` kills whichever tick later reads
    it as an image.
    """
    url = getattr(value, "url", value)
    if not isinstance(url, str):
        return None
    return url if urlparse(url).scheme in {"http", "https"} else None


def _filename_from_url(url: str, idx: int) -> str:
    name = Path(urlparse(url).path).name
    return name or f"output-{idx}"


# An error body is the thing we must never write under a media extension.
_TEXT_TYPES = ("application/json", "text/")


def _reject_reason(response: httpx.Response) -> str | None:
    """Why this response must not be written to disk, or None if it is fine."""
    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type.startswith(_TEXT_TYPES):
        return f"served {content_type or 'no content-type'}, not media"
    body = response.content
    if not body:
        return "empty body"
    if body.lstrip()[:1] in (b"{", b"["):
        return "body looks like JSON, not media"
    return None


@app.command()
def run(
    model: str = typer.Argument(..., help="owner/name or owner/name:version"),
    input: list[str] = typer.Option([], "--input", help="Model input as key=value (repeatable)"),
    output: Path = typer.Option(Path("assets"), "--output", help="Directory for downloaded media"),
):
    """Run a Replicate model with --input k=v ... and download any media."""
    if not os.environ.get("REPLICATE_API_TOKEN"):
        typer.echo("error: REPLICATE_API_TOKEN env var is required", err=True)
        raise typer.Exit(code=1)

    if output.suffix:
        typer.echo(
            f"error: --output is a directory, not a file (got {output}). "
            "Media keeps the model's own filename inside it.",
            err=True,
        )
        raise typer.Exit(code=2)

    inputs = _parse_input(input)
    result = replicate.run(model, input=inputs)

    items = result if isinstance(result, list) else [result]
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    failed = 0
    for idx, item in enumerate(items):
        url = _url_of(item)
        if url is None:
            typer.echo(item if isinstance(item, str) else str(item))
            continue

        response = httpx.get(url, follow_redirects=True)
        response.raise_for_status()
        reason = _reject_reason(response)
        if reason is not None:
            typer.echo(f"error: refusing to save {url} --- {reason}", err=True)
            failed += 1
            continue

        target = output / _filename_from_url(url, idx)
        target.write_bytes(response.content)
        typer.echo(str(target))

    if failed:
        raise typer.Exit(code=1)


@app.command()
def cookbook():
    """Print worked recipes for running and exploring Replicate models.

    Lives as a subcommand (not in `--help`) because typer's help renderer
    collapses whitespace and would mangle the shell snippets.
    """
    typer.echo(COOKBOOK)
