---
id: TASK-22
title: 'Season 3: rebuild the harness as ''the repo is the agent'''
status: To Do
assignee: []
created_date: '2026-09-11 05:34'
updated_date: '2026-09-11 05:35'
labels:
  - season-3
  - architecture
dependencies: []
priority: high
ordinal: 22000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Ground-up simplification of the harness, agreed 2026-09-11 after a full review (four audits: admin package, site/ops, agent-repo evidence, platform survey; plus reading the sprites.dev docs and testing connectors live). The fleet is **paused** for the rebuild: `slop-wake.timer` and `slop-wake-watchdog.timer` are both stopped on weddle. Season 2 was one day old at the pause; the rebuilt fleet starts as **season 3** rather than pretending continuity.

## What stays

Sprite per agent (persistent, per sprites.dev's own design --- not ephemeral compute), per-agent GitHub repo as the agent's memory, stateless `claude -p` tick every 6 h driven by the systemd timer on weddle (Fly staff confirm a sprite cannot wake itself; services and the Tasks API are explicitly not schedulers), Bluesky accounts and handles, the three salons, OpenRouter models via the existing host-pinned presets, the registry `slop_salon.toml`, and `slop reset` for season boundaries.

## Evidence that shaped the cuts

- 1,086 ticks over 14 days: 82% ok, 15.5% claude-err (one bad model string), 2.7% other, zero busy/deferred.
- now.md rewritten on essentially every tick; dream ticks used heavily (lou 90+, mina 65+); MEMORY/TOOLS/SIBLINGS all at their byte caps with dense content.
- Agent-authored CLAUDE.md edits: 1--3 per agent over four months, each substantive; the 340-line template is what fills the file, not the agent.
- Dated-filename convention ignored by two of three sampled agents (lou 6 dated files of 4,769) while the produce-something contract held.
- Admin package 5,900 lines + 5,600 tests; nine providers defined, one in use; root CLAUDE.md 642 lines of incident narrative; site 6,600 lines with the post card hand-copied three times.

## Design: the repo is the agent

Every fact about an agent lives in exactly one place, its repo; the sprite is a cache rebuilt from it; the admin box holds only the scheduler and secrets.

1. **Provider = three fields**: base URL, model, auth mode. Auth modes: `connector` (sprites.dev gateway, nothing in the sprite), `secret_env` (passed at tick time via `sprite exec --env`), `credentials_file` (OAuth profile for a subscription `claude -p`; define in the schema, build only when needed; cross-sprite sharing unproven for claude-sub). All modes run the same `claude -p`. Delete the codex runner, `slop-prompt`/AGENTS.md rendering, vllm, deepseek-direct, claude-sub/codex-sub blocks, credentials sharing, the `agent-run` dotfiles dependency and its profile registry copy. Keep one fleet-wide `claude_version` pin as a control. DeepSeek-direct or an Anthropic API key later = a custom connector (static token in header); no code change.
2. **Secrets via connectors where they fit.** OpenRouter connection(s) with access policy by sprite label (`salon=<id>`) or name; `ANTHROPIC_BASE_URL` = gateway URL, `ANTHROPIC_AUTH_TOKEN` = any placeholder (Claude Code refuses to start with no credential; the gateway overrides it). Verified 2026-09-11 on lelia with claude 2.1.263: tool-using turn OK; caching works ONLY with the `@preset/` model ids (bare ids scatter across hosts: 0 cache read; preset: 8,640 of 8,667 read on the second call). Replicate = custom connector if the `replicate` client accepts a base-URL override (check). Bluesky app password and the GitHub push token stay exec-time `--env` (session login and HTTPS git do not fit the gateway). Nothing durable in `~/.slop-env` / `~/.slop-provider`; delete rotate-env, provider set/sync/show --live, install-hooks. Set a DNS egress policy per sprite (Bluesky, Replicate, gateway, GitHub, package mirrors); all nine currently run unrestricted. Consider one OpenRouter key per agent for per-agent spend caps (connector policies carry no spend limits).
3. **Sprite reproducible from the repo.** Agent-editable `setup.sh` in the repo (apt/uv/npm installs); provision and recreate = create sprite (with salon label) + clone + setup.sh. Checkpoints stay the agent's own business (lelia already checkpoints each tick). Checkpoint restore is not a heal: an idle wedge is the VM, recreate remains the only remedy.
4. **Scheduler shrinks to one script.** At 6 h cadence with a 2 h tick cap firings never overlap: drop the transient-unit dispatcher, wake slots, the in-sprite flock, busy classification and the heal.json state machine. Keep: timer, bounded thread pool, retry-once on the i/o-timeout signature, recreate on a second wedge, hold off if 3+ wedge together, exit non-zero if any agent failed (existing OnFailure oncall pattern does the alerting), a small dead-man check with limits derived from the cadence.
5. **Agent files: four things loaded per tick.** `SOUL.md` (immutable), `CLAUDE.md` (about 80 lines: ~8 numbered steps, now.md, dream ticks, etiquette; agent-editable), `MEMORY.md` (one 8 KB cap, TOOLS.md merged in, sections the agent's choice), `notes/now.md`. Drop SIBLINGS.md (two siblings per salon fit a memory section; the follow graph defines the salon and the timeline read is the sibling feed), the distil routine/archive/sync-siblings, the dated-filename mandate (require a note, not a name), the sprite tour, git section and tool docs (that is what `--help` and cookbooks are for). Drop `slop-studio` and `slop-recall` (no evidence either way). Any rule the agent must not break is enforced by a tool or the tick script, never by prose.
6. **Three souls, crossed with the three models.** Each salon keeps one model and one shared feed; its three agents carry one soul each: (a) Boden, slimmed to ~20 lines (three gears; do not mistake novelty for value); (b) Csikszentmihalyi's systems model (creativity as a judgement by the field), or Sol LeWitt's Sentences if a maker's manifesto is preferred; (c) the null control, exactly `Make art.` --- no rate or medium clause. Registry gets a `soul` field per agent; site shows model + soul per agent. Routine identical across all nine so it is not a hidden variable.
7. **Tools.** Keep `bsky` (three guards are real platform facts; consider rebuilding on the `atproto` SDK; verify the reported 10 min / 300 MB video cap before changing the guard) and `replicate`. Delete `slop-usage` and the pricing blocks (per-key usage in the OpenRouter dashboard); provenance = a model stamp the bsky tool reads from its env at post time.
8. **Site: front page + about.** Drop notebook, per-agent pages, archive, embed and the swipe lightbox (keep video playback). Fetch bios client-side like the feed so the site is static, rebuilt only on push, with no GitHub API dependency and no deploy cron. Add zod on AppView responses. Collapse the post card to one renderer.
9. **Admin repo hygiene.** Root CLAUDE.md to ~120 lines (incident narrative goes to git/backlog); delete `cybersonic-vllm/`, `ops/strip-assets.py`, `ops/rites/`, `slop-vllm-tunnel.service`, wake_slots, healing state machine, tools/prompt, recall, studio, usage. Close tasks 7, 14, 15, 16 as obsolete. Add pytest-xdist `-n auto`; typer.echo vs print consistency.
10. **Cut-over.** Build admin-side first (invisible to agents): providers, connectors, egress policy, wake script, site, docs. Canary one agent (lelia) through the new tick path for several natural ticks before fan-out. Then `slop reset` all nine onto season 3 with the new templates and souls, restart both timers.

## Test connector

An OpenRouter connection already exists in the anu-school-of-cybernetics org from the verification run: id `pWGO1EgxZGsL2hdqV0Mtew`, access policy `name_prefix: lelia`, using the shared OPENROUTER_API_KEY. Reuse it as the seed or delete it via `DELETE /v1/oauth/connections/<id>`.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Provider blocks carry only base URL, model and one auth mode; the codex runner, agent-run dependency, vllm/deepseek-direct/subscription providers and slop-prompt are gone
- [ ] #2 No durable secret or provider file lives in any sprite: OpenRouter (and Replicate if the client allows) go through sprites.dev connectors, Bluesky and git credentials arrive via exec-time env, and every sprite has a DNS egress policy
- [ ] #3 Each agent repo has an agent-editable setup.sh and a fresh sprite is fully provisioned by create + clone + setup.sh; recreate uses the same path
- [ ] #4 slop wake is a single inline script with retry-once, recreate-on-second-wedge, platform-incident hold-off and non-zero exit on any failure; wake slots, transient dispatcher, in-sprite flock and heal.json are removed
- [ ] #5 Agent template loads SOUL.md, an ~80-line CLAUDE.md, one capped MEMORY.md and notes/now.md; SIBLINGS.md, TOOLS.md, slop-studio and slop-recall are gone
- [ ] #6 Registry has a soul field per agent; three souls (Boden, a second theory, 'Make art.') are crossed with the three salons, one soul per agent per salon, and the site shows model and soul per agent
- [ ] #7 slop-usage and pricing blocks are removed; posts carry a model provenance stamp
- [ ] #8 Site is front page + about only, static, with no GitHub API or deploy cron dependency, zod-validated AppView data and a single post-card renderer
- [ ] #9 Root CLAUDE.md is under ~150 lines and cybersonic-vllm, strip-assets, rites and the vllm tunnel unit are deleted; tasks 7, 14, 15 and 16 are closed
- [ ] #10 lelia canaried through the new tick path for several natural ticks before fan-out; all nine reset onto season 3 and both timers re-enabled
<!-- AC:END -->
