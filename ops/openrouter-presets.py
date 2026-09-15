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
    # V4.1 Flash: natively multimodal, first-party only. The pin matters even
    # though DeepSeek is currently the sole host --- OpenRouter adds third-party
    # hosts to a popular model within days, and this salon should not drift onto
    # one silently.
    "slop-deepseek-v41": {
        "model": "deepseek/deepseek-v4.1-flash",
        "provider": {"only": ["deepseek"]},
    },
    # The vision-capable V4 Flash (V4 Flash text-only 404s on any image input,
    # which killed every DeepSeek tick that Read a PNG). `order` with `only` is a
    # priority list, not load balancing, and `allow_fallbacks: false` still
    # walks it --- it only forbids hosts outside `only`. DeepInfra 422s any
    # request carrying an image tool_result, so once a tick Reads a PNG every
    # request lands on Fireworks, and a Fireworks blip used to kill the tick
    # with DeepInfra's 422. GMICloud (fp8, twice list price, caches) is the
    # verified backstop; `/fp8` pins that endpoint so a later fp4 one can't
    # join. SiliconFlow also passed but caches only 512 tokens; AtlasCloud 400s
    # on images (measured 2026-09-15).
    "slop-deepseek-vision": {
        "model": "deepseek/deepseek-v4-flash-vision-exp",
        "provider": {
            "order": ["deepinfra", "fireworks", "gmicloud/fp8"],
            "only": ["deepinfra", "fireworks", "gmicloud/fp8"],
            "allow_fallbacks": False,
        },
    },
    # Z.AI first; the rest only when it 429s or stalls, which it did through
    # 2026-09-14/15 with no fallback to take the tick. Fallbacks are fp8 hosts
    # that passed Claude Code's captured request shape with tools and images,
    # render transparent PNGs the way Z.AI does, cache, and cost list price or
    # less (measured 2026-09-15).
    "slop-glm-flash": {
        "model": "z-ai/glm-5.3-flash",
        "provider": {
            "order": ["z-ai", "streamlake/fp8", "gmicloud/fp8", "atlas-cloud/fp8"],
            "only": ["z-ai", "streamlake/fp8", "gmicloud/fp8", "atlas-cloud/fp8"],
            "allow_fallbacks": False,
        },
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
