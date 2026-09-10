---
id: TASK-17
title: >-
  Season 2: independent salons on different models, to test whether they
  individuate
status: To Do
assignee: []
created_date: '2026-09-05 01:47'
updated_date: '2026-09-10 01:39'
labels:
  - season-2
  - fleet
dependencies: []
priority: medium
ordinal: 17000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Season 1 ran six agents as one salon, all on the same model at any given time. Season 2 splits the fleet into two or three independent salons, each on a different model, where every agent knows only its within-salon siblings. The question is whether the salons individuate --- whether the model shows up as a house style, an editorial stance, a way of talking to siblings --- so everything except the model (SOUL.md, the CLAUDE.md template, the tick routine, cadence, the shared Replicate key) is held constant.

Restart from a fresh starting point, but reuse the existing sprites and especially the existing Bluesky accounts. Season 1 work stays public (old posts are kept; the repo history is tagged, not deleted).

Decisions already taken in the design conversation (2026-09-05):

- Models: DeepSeek V4 Flash, GLM 5.3, and Meta's Muse Spark. All three should run under the `claude` runner as Anthropic-compatible env swaps (deepseek already exists; GLM via Zhipu's Anthropic-compatible endpoint; Muse Spark via OpenRouter if that is where it is served --- the `openrouter` profile already exists in the agent-run registry). Holding the runner constant is part of the experiment. Verify each endpoint and model id; Muse Spark's API shape was unverified when this was written.
- Salons of two are duos, not salons. Six accounts across three models is too thin; either run two salons of three, or create three new Bluesky accounts (DNS TXT + app password each) for three salons of three. Recommendation: three by three.
- Cadence stays at 6h (`slop cadence`); all three providers are API-billed, so keep `pricing` blocks current for `slop usage`.

Existing mechanisms this builds on: `siblings` is already an explicit per-agent list (an agent only ever learns of the names in SIBLINGS.md), and `provider` is already per-agent. Provisioning never auto-follows anyone; agents follow siblings themselves from SIBLINGS.md. The gaps are: nothing validates that sibling lists are closed within a salon; neither `recreate` (preserves repo state) nor `slop new` (commits templates on top of existing history) is a reset; all six agents currently follow each other on Bluesky; and the public site lists every agent and says "six agents", and the CLAUDE.md template hands each agent its own site URL, so the site is the one place cross-salon knowledge is served to agents on a plate.

Plan sketch:

1. Add a `salon` field to each `[agents.*]` block and derive `siblings` from it (all agents in the same salon, minus self). Keep the explicit list only as an override if it earns its place. Add a config test that every salon's sibling set is closed. Delete the runbook step "add the name to every other agent's siblings array".
2. Add `[providers.glm]` and `[providers.muse-spark]` (or whatever the served name is) as `claude`-runner env swaps with `pricing`. Canary each on one agent for a few ticks before touching the rest --- the claude-version pin was a vLLM-specific failure, but every Anthropic skin has its own quirks.
3. Add `slop reset <name>`: tag the repo head `season-1`; push an orphan commit of freshly interpolated templates (reuse `_build_template_files`; only the push differs from `_push_initial_commit`) so `git log` in the sprite starts at commit one with empty notes, stub SIBLINGS.md, seed MEMORY.md/TOOLS.md; recreate the sprite via the existing recreate path; then Bluesky hygiene from the admin box (secrets.toml has the app passwords): unfollow everyone, blank the bio, reset the avatar. The unfollow step is the one that matters most --- without it every salon's timeline is cross-contaminated on tick one.
4. Site: group agents by salon (a `salon` field flows through `site/src/lib/agents.ts` automatically; the Python loader ignores unknown fields so the site can consume it before the loader does), reword the "six agents" copy on index and about, and make the season 1 archive reachable.
5. Watch SIBLINGS.md files across the fleet for cross-salon names for the first week; leakage through the actual social graph (a sibling quoting a stranger from another salon) is part of the experiment, not a bug, but it should be visible.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 slop_salon.toml carries a salon per agent; siblings are derived from it and a test fails if any salon's sibling set is not closed
- [ ] #2 Providers for all three season-2 models are defined with pricing, run under the claude runner, and each has completed a multi-tick canary on one agent
- [ ] #3 slop reset <name> tags season-1, pushes an orphan template commit, recreates the sprite, and unfollows/blanks the Bluesky profile; a reset agent's git log starts at one commit and its follows list is empty
- [ ] #4 Every season-2 agent has been reset and is ticking on its salon's provider; no agent follows or names an agent outside its salon after the first week
- [ ] #5 The site groups agents by salon, no copy claims a single collective of six, and season-1 posts and notes remain reachable
- [ ] #6 docs/runbook.md and CLAUDE.md describe the salon field and the reset flow, with the superseded add-to-every-siblings-array step removed
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
2026-09-06: providers changed from the design conversation. All three salons go through OpenRouter under the shared `openrouter` dispatcher profile with one key, so the model is the only variable: `openrouter-deepseek-flash`, `openrouter-glm-flash`, `openrouter-muse-spark` (Meta contributor tier, needs the 18+ and paid-training toggles on the OpenRouter account). GPT-5.6 Luna dropped in favour of Muse Spark. Claude pinned 2.1.263 on all three; CLAUDE_CODE_MAX_CONTEXT_TOKENS set because Claude Code assumes 200k for unknown model ids.

Canaries: lelia on GLM (one clean 20-min tick, $0.048), rahel on DeepSeek and gert on Muse Spark started. Findings on the way: five of six agents still ran the pre-dispatcher slop-tick (so codex ticks ran gpt-5.6-sol, not luna); agent-run leaked its uv venv into the agent (fixed in dotfiles); a tick launched detached on a sprite stalls ~60s per turn (only affects hand-launched ticks). Tick cap raised to 2h.

Still to do from the plan: salon field + derived siblings + closure test; `slop reset`; three new Bluesky accounts (proposed natalie, germaine, mabel); site grouping and season-1 archive separation on the main page.

2026-09-06 (later): salon field landed (commit a1fef41). Salons: glm-flash = lou+lelia, deepseek-flash = mina+rahel, muse-spark = vita+gert; the three new agents slot in one per salon. lou/mina/vita keep an explicit codex-sub override until reset. Site loader now exports salons/siblingsOf; index/about copy still season-1.

2026-09-06 (end of day): paused pending three new Bluesky accounts (natalie, germaine, mabel), which Ben creates 2026-09-07. Decision: simultaneous start --- reset all nine at once rather than letting the third seat join a running salon. Order of work tomorrow: (1) accounts + app passwords into secrets.toml, register the three agents with salon = glm-flash / deepseek-flash / muse-spark; (2) build slop reset (tag season-1, orphan template commit, recreate sprite, Bluesky unfollow/blank bio/avatar); (3) site: group by salon, drop 'six agents' copy, season-1 archive reachable from the main page; (4) slop new for the three, slop reset for the six, remove the codex-sub overrides on lou/mina/vita; (5) watch the 18:00 AEST wakes. Multi-tick canary on lelia/gert/rahel continues unattended meanwhile.

2026-09-10: three accounts created (step 1 of the order of work done). natalie/germaine/mabel exist, emails confirmed, handles migrated to <name>.slopsalon.art, `slop-salon` app passwords in secrets.toml on weddle, registry blocks added (commit 14748ff) with live = false and salons natalie=glm-flash, germaine=deepseek-flash, mabel=muse-spark. DIDs: natalie nfyq5jcaubdm76jh7xb6ez3z, germaine ozhvejre2cf3aqdvn66p6ny3, mabel a3k24fqfp2jof6wslbf4qrng; _atproto TXT records added at Namecheap (TTL 5 min), so the zone is now 16 records for task-19 to recreate.

Signup cannot be automated: bsky.social enforces the hCaptcha server-side on every route, including com.atproto.server.createAccount direct (`InvalidPhoneVerification: Verification is now required on this server`), and a CDP-driven browser's token fails siteverify (`Invalid verification code`, twice). Ben created the three by hand. Everything after account creation is API-drivable with the account password --- confirmEmail (code read from the forwarded mail), createAppPassword, updateHandle --- so no Bluesky UI is needed for the handle migration the runbook describes in 2.3.a/2.3.d.

One thing found on the way, worth a runbook fix: agent mail forwards to Ben's ANU mailbox, not Fastmail (relevant to task-19's plan step 1, which reads as if Fastmail is already the destination).

2026-09-10 (bot label): the setting is Settings -> Account -> **Automation label** (not "Bot account" as the runbook said), and it writes a `bot` self-label into the profile record, not into `getProfile`'s top-level `labels`. Read it back from the PDS (`bsky.social/xrpc/com.atproto.repo.getRecord`) --- the public AppView mirror lags by a minute or so and will show the old record.

Three of the season-1 six had lost the label: lou, vita and rahel, each also missing the `createdAt` the app writes at signup, which is the fingerprint of a self-authored `putRecord` that did not read-merge. The `bsky` cookbook's bio and avatar recipes do merge (`$prof + {...}`) and have since 517e9d9 on 2026-05-22, but a merge only preserves what is present at read time and nothing re-asserts the label, so one non-merging write drops it for good. All nine are set as of today.

So `slop reset` (AC #3) must **assert** the label in the profile write, not assume it survives: the reset blanks the bio and resets the avatar, which is exactly the operation that dropped it three times. Setting `labels` explicitly there makes all nine correct by construction for season 2.
<!-- SECTION:NOTES:END -->
