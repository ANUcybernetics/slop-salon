#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx"]
# ///
"""Create or update the OpenRouter presets the season-2 providers route through.

OpenRouter fans a model out across many hosts, and some of them answer Claude
Code's request shape with an empty message (DeepSeek V4 Flash on StreamLake,
Parasail, Azure, and intermittently DigitalOcean and SiliconFlow, measured
2026-09-06). Claude Code cannot put a `provider` routing object in the request
body, so the routing lives in a preset and the provider block names it in the
model string: `deepseek/deepseek-v4-flash@preset/slop-deepseek-flash`.

Idempotent: POSTing to /presets/<slug>/messages creates or updates the preset,
persisting only the configuration fields (the tiny inference it runs is the
price of the API). Needs OPENROUTER_API_KEY in the environment.

    mise exec -- uv run ops/openrouter-presets.py
"""

from __future__ import annotations

import os
import sys

import httpx

PRESETS = {
    # Hosts that returned a real reply on every one of four tries with Claude
    # Code's captured request body; fp4 hosts left out so the salon runs the
    # model at fp8 or better.
    "slop-deepseek-flash": {
        "model": "deepseek/deepseek-v4-flash",
        "provider": {
            "only": [
                "deepinfra",
                "baidu",
                "gmicloud",
                "alibaba",
                "venice",
                "nextbit",
                "novita",
                "phala",
            ]
        },
    },
    # The vision-capable V4 Flash (V4 Flash text-only 404s on any image input,
    # which killed every DeepSeek tick that Read a PNG). DeepInfra and Fireworks
    # serve it at list price; SiliconFlow, AtlasCloud and Novita charge double.
    "slop-deepseek-vision": {
        "model": "deepseek/deepseek-v4-flash-vision-exp",
        "provider": {"only": ["deepinfra", "fireworks"]},
    },
    # First-party only.
    "slop-glm-flash": {
        "model": "z-ai/glm-5.3-flash",
        "provider": {"only": ["z-ai"]},
    },
}


def main() -> None:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        sys.exit("OPENROUTER_API_KEY is not set")
    headers = {"Authorization": f"Bearer {key}", "anthropic-version": "2023-06-01"}
    for slug, config in PRESETS.items():
        body = {
            **config,
            "max_tokens": 5,
            "messages": [{"role": "user", "content": "hi"}],
        }
        response = httpx.post(
            f"https://openrouter.ai/api/v1/presets/{slug}/messages",
            headers=headers,
            json=body,
            timeout=60,
        )
        response.raise_for_status()
        print(f"{slug}: {config['provider']}")


if __name__ == "__main__":
    main()
