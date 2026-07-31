# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx", "pillow"]
# ///
"""Build the mosaic plates: agents down the page, their work across it, tiled
as square cells. Fetches from the Bluesky public API.

Two layouts, both full-page against the style's 5.5x9in text block:

  (default)  figures/mosaic.jpg --- 12x3 per agent, 216 works. Dense enough to
             read as texture: you see each agent's palette and the shared
             late-season drift, but not individual works.
  --detail   figures/mosaic-detail.jpg --- 4x1 per agent, 24 works at roughly
             3x the linear size, so individual pieces are legible. Columns are
             even samples through the season, so they read early to late and
             show the individuation the dense plate can only imply.

Adapted from blowing-smoke/2026-anu-promotion/make-mosaic.py, which was laid
out 7x6 (near-square) for a CV.

Season one ended 2026-07-27, so the feeds are static now --- but this still
needs the network, so the outputs are tracked rather than built by the Makefile.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont

API = "https://public.api.bsky.app/xrpc"

# Block order matches the site's listing, and the captions in main.tex.
AGENTS = ["lou", "mina", "gert", "vita", "lelia", "rahel"]
GAP = 12  # white gutter between agent blocks
LABEL_W = 200  # left strip carrying the agent name
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"
HERE = Path(__file__).parent

# cols, rows-per-agent, cell px, output. Both land near 5.5x7.8in at
# \textwidth, leaving the caption its ~0.9in of the 9in text block.
LAYOUTS = {
    "dense": (12, 3, 220, HERE / "mosaic.jpg"),
    "detail": (4, 1, 600, HERE / "mosaic-detail.jpg"),
}


def all_images(client: httpx.Client, handle: str, cap: int | None = None) -> list[str]:
    """Return fullsize image URLs for one agent, newest first.

    Stops early at `cap` when only the recent tail is wanted.
    """
    urls: list[str] = []
    cursor = None
    while cap is None or len(urls) < cap:
        params = {
            "actor": f"{handle}.slopsalon.art",
            "filter": "posts_with_media",
            "limit": 100,
        }
        if cursor:
            params["cursor"] = cursor
        r = client.get(f"{API}/app.bsky.feed.getAuthorFeed", params=params)
        r.raise_for_status()
        data = r.json()
        for item in data.get("feed", []):
            embed = item["post"].get("embed", {}) or {}
            images = embed.get("images") or (embed.get("media", {}) or {}).get("images")
            if images:
                urls.append(images[0]["fullsize"])  # one work per post
            if cap is not None and len(urls) >= cap:
                break
        cursor = data.get("cursor")
        if not cursor:
            break
    return urls[:cap] if cap else urls


def pick(urls_newest_first: list[str], n: int, spread: bool) -> list[str]:
    """Choose n images for a row, ordered oldest to newest (left to right).

    spread=False takes the most recent n --- an end-of-season snapshot.
    spread=True samples evenly across the agent's whole history, so a row
    reads as a timeline and shows the practice individuating.
    """
    oldest_first = list(reversed(urls_newest_first))
    if not oldest_first:
        return []
    if not spread:
        return oldest_first[-n:]
    if len(oldest_first) <= n:
        return oldest_first
    step = (len(oldest_first) - 1) / (n - 1)
    return [oldest_first[round(i * step)] for i in range(n)]


def square(img: Image.Image, size: int) -> Image.Image:
    """Centre-crop to square, then resize to size x size."""
    w, h = img.size
    side = min(w, h)
    left, top = (w - side) // 2, (h - side) // 2
    img = img.crop((left, top, left + side, top + side))
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    # Spread is the default: the end-of-season tail alone reads as convergence
    # (all six drifted toward technical plots late on), which undersells the
    # individuation the figure is there to show. Pass --recent for that variant.
    spread = "--recent" not in sys.argv
    cols, rows_per_agent, cell, default_out = LAYOUTS[
        "detail" if "--detail" in sys.argv else "dense"
    ]
    per_agent = cols * rows_per_agent
    positional = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = Path(positional[0]) if positional else default_out

    block_h = cell * rows_per_agent
    width = LABEL_W + cols * cell
    height = len(AGENTS) * block_h + (len(AGENTS) - 1) * GAP
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(FONT, round(width / 55))

    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for i, handle in enumerate(AGENTS):
            pool = all_images(client, handle, cap=None if spread else per_agent)
            urls = pick(pool, per_agent, spread)
            print(f"{handle}: {len(urls)} of {len(pool)} images", file=sys.stderr)

            top = i * (block_h + GAP)
            draw.text(
                (LABEL_W - 24, top + block_h // 2),
                handle,
                font=font,
                fill="#0b0b0b",
                anchor="rm",
            )
            for j, url in enumerate(urls):
                resp = client.get(url)
                resp.raise_for_status()
                tile = square(Image.open(io.BytesIO(resp.content)).convert("RGB"), cell)
                x = LABEL_W + (j % cols) * cell
                y = top + (j // cols) * cell
                canvas.paste(tile, (x, y))

    canvas.save(out, "JPEG", quality=88, optimize=True)
    print(f"wrote {out} ({canvas.size[0]}x{canvas.size[1]})", file=sys.stderr)


if __name__ == "__main__":
    main()
