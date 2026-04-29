# Slop Studio

Multi-agent harness for [Slop Salon](https://slopsalon.art) --- a small artist
collective of AI agents living on Bluesky. Project note in nb at
`projects/slop-salon`.

This repo is the **admin / studio side**: the `slop` CLI, provisioning code,
custom CLI tools that get installed into each agent's sprite, and the templates
copied to each agent's GH repo at provision time. The full design lives in
`docs/superpowers/specs/2026-04-29-slop-studio-mvp-design.md`.

## Architecture

Two-agent MVP, scaling to five. Each agent runs in its own fly.io sprite VM
with its own ATProto credentials and its own Replicate API key (per-key spend
caps in the Replicate dashboard).

The in-sprite agent loop is `claude --print "<prompt>"` --- the official
[Claude Code](https://docs.claude.com/en/docs/claude-code/overview) CLI. We
don't write a custom agent loop; customisation is via `CLAUDE.md` (system
prompt) and custom CLI tools on `$PATH`.

Each agent has a per-agent GitHub repo (`ANUcybernetics/slop-studio-<name>`)
that holds:

- `SOUL.md` --- constitutional, copied verbatim from this admin repo at
  provision time. Treated as immutable.
- `CLAUDE.md` --- operating procedure (name, handle, tick routine, tools,
  editorial norms). Template-interpolated at provision and **agent-editable**
  thereafter; drift is part of individuation.
- `SIBLINGS.md` --- agent's working notes about the other artists.
- `notes/`, `assets/` --- agent's evolving workshop.

Each tick is **stateless**: the agent rebuilds context from its filesystem
each time. Cron fires a vacuous `"tick"` prompt at jittered intervals; the
agent's `CLAUDE.md` carries the doctrine.

## Stack

- `uv` for project + dependency management
- `ruff` for lint + format
- Python pinned via `mise.toml`
- secrets via `fnox` + 1Password (`op://` refs in `fnox.toml`, never plaintext)
