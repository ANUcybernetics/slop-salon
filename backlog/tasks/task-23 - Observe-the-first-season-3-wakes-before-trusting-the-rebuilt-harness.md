---
id: TASK-23
title: Observe the first season-3 wakes before trusting the rebuilt harness
status: To Do
assignee: []
created_date: '2026-09-11 07:05'
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
