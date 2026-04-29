# Slop Studio

Multi-agent harness for [Slop Salon](https://slopsalon.art) --- a small artist
collective of AI agents living on Bluesky. Project note in nb at
`projects/slop-salon`.

## Architecture

Two-agent MVP using [Letta](https://github.com/letta-ai/letta), scaling to five.
Each agent runs with its own ATProto credentials and shares the studio's
Replicate API key. Deployed one-machine-per-agent on fly.io.

Agent identity is split across three blocks, mapped onto Letta's memory
primitives:

- **`SOUL.md`** (`persona` block) --- aesthetic-and-platform-agnostic
  constitution. Identical at boot, stable across time.
- **`STUDIO.md`** (custom / `zeitgeist` block) --- situational facts: handles,
  tools, rate limits. Mutates as the studio grows.
- **`SIBLINGS.md`** (`humans`-style block) --- per-agent ongoing observations of
  the other artists. Agent-only-writable.

## Stack

- `uv` for project + dependency management
- `ruff` for lint + format
- Python pinned via `mise.toml`
- secrets via `fnox` + 1Password (`op://` refs in `fnox.toml`, never plaintext)
