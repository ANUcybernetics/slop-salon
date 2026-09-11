---
id: TASK-23
title: Observe the first season-3 wakes before trusting the rebuilt harness
status: To Do
assignee: []
created_date: '2026-09-11 07:05'
updated_date: '2026-09-11 10:04'
labels:
  - season-3
  - ops
dependencies: []
priority: high
ordinal: 23000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Task-22 fanned out after a single manual canary tick on lelia rather than several natural 6-hourly ones. The first scheduled wakes (18:00 and 00:00 AEST on 2026-09-11/12, then onward) are the real observation gate. Check them, and fix or file anything that surfaces before touching the harness again.

What to look at per wake:
- journalctl --user -u slop-wake.service -n 120: one line per agent, all ok; note any claude-err, wedge or fail(<code>) and its error tail. A fail(128) is a merge conflict; a 401/403 is the connector policy or a missing slop label.
- ~/.local/state/slop/last-wake.json and wedges.json: stamp fresh, counters at 0.
- slop wake-check exits 0 and slop-wake-watchdog.service filed no oncall todo.
- Salon closure: for each agent, listRecords app.bsky.graph.follow is exactly the two siblings, and no post replies to, quotes or mentions an artist in another salon (the bsky guard should make this impossible; confirm it held under a real model rather than a test).
- Provenance: new feed posts carry provenance = {model, salon} and the site shows the model tag on those cards.
- Repos: each agent pushed (no unpushed commits in the sprite; slop diff <name> --since 6.hours), SOUL.md clean under slop drift -f SOUL.md, CLAUDE.md/setup.sh drift noted but not reverted.
- Cost: per-model spend on the OpenRouter dashboard after a full day, since slop-usage is gone; DeepSeek is expected to be the dear salon.

Known gaps to keep in mind (open by design, worth a task if they bite): wake-check only flags a wake in which every agent failed, so one dead agent never trips it; the wake unit's OnFailure covers a red run but not a stuck one under TimeoutStartSec=3h; REPLICATE_API_TOKEN still rides in the tick env because the sprites.dev custom-API connector rejects the key.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Two consecutive scheduled wakes have completed with every agent ok, or every failure has been diagnosed and either fixed or filed
- [ ] #2 Every agent's follow graph is still exactly its two siblings and no cross-salon interaction appears in any season-3 post
- [ ] #3 New posts carry the provenance stamp and the site renders the model tag
- [ ] #4 First-day spend per salon read off the OpenRouter dashboard and recorded here
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
2026-09-11, wake one (18:02 AEST): 7/9 ok. lou and vita died at 31.4s and 23.8s
with `Error: connection closed` and no transcript --- the tick never started.
Not retried and not counted, because that string was not in `_WEDGE_MARKERS`;
task-17 recorded the same string three times in season 2 and left the retry
question open.

Root cause: resuming a cold sprite takes ~30s (measured: a genuinely cold
resume reached `session_created` at 29.03s, against <2s warm) and the platform
sometimes drops the connection while it does. Both failures were in the wake's
first concurrency batch, four cold resumes at once; the five that started later
against an already-busy platform all succeeded. Ruled out by testing against
the live fleet: idle/keepalive timeout (90s silent exec fine; 15s pings, 45s
deadline), env payload (uniform 861-941 B), concurrency alone (9 concurrent
real-env execs, 9/9 ok), git pull + claude startup + the gateway (9/9 ok), OOM
(8 GB, no kills), claude auto-update (pinned 2.1.263 everywhere).

Fixed 42f49b1: the exec command now echoes SESSION_MARKER before `slop-tick`,
and `never_started` asks for that marker instead of matching the platform's
error text. Only a tick that provably never ran is retried; one that started
and then dropped is left alone, since its `claude` may still be running in the
sprite. Marker rides on the admin-side command, so no agent-repo rollout.

Also: sprite CLI was rc43 (11 May) against rc48 servers --- upgraded, and
b30dd2e passes rc48's new --no-port-forward (probed from --help, not
hardcoded). Repaired ~/.sprites/known_sprites.json, corrupt with a trailing
'}' from concurrent CLI writes since 2026-07-25.

AC status after wake one: #2 follows are exactly the two siblings on all nine
and no cross-salon reference in any season-3 post; #3 provenance present on
every agent-authored post and the site renders the model tags --- but the nine
"season 3 starts here" markers, posted admin-side by `slop reset`, carry no
provenance and show as untagged cards. #4 not readable: the mise
OPENROUTER_API_KEY is an inference key and /api/v1/activity needs a management
key; account total is $20.99 of $300. #1 still owed a second clean wake.
<!-- SECTION:NOTES:END -->
