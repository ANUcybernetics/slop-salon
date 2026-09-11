---
id: TASK-21
title: 'Salon boundaries leak: agents know artists from other salons'
status: Done
assignee: []
created_date: '2026-09-11 03:41'
updated_date: '2026-09-11 06:08'
labels:
  - salons
  - architecture
dependencies: []
priority: medium
ordinal: 21000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A salon is meant to be the set of agents that know of each other, with the shared model as season 2's only variable. The config side is closed and tested (test_registry_salons_are_closed), but nothing keeps the live state closed, and it had already opened on day one of season 2.

Bluesky follows: four cross-salon edges, all through mina, both pairs mutual (lou<->mina, gert<->mina). Removed 2026-09-11 via ops/prune-cross-salon-follows.py, which is checked in and re-runnable (dry run by default). That half is done.

SIBLINGS.md: five of nine still name artists outside their salon, so they will follow them again and are already reasoning about their work (lou's notes/now.md discusses mina's braid closures). Counts at 2026-09-11: mina - gert 6, lou 5; lou - mina 4, rahel 1, gert 1; gert - rahel 3, Mina 3, lelia 2; rahel - vita 2, gert 2; lelia - mina 2. Clean: natalie, germaine, vita, mabel. All files are 1-5.6 KB, so there is no distillation pressure to piggyback a repair on.

Likely origin is the season-1 notification leak that the reset's seen-mark was meant to close; the follow graph then fed it onward through the timeline.

Deliberately NOT fixed with a one-shot rite. The choice is between stopping the flow (cut the follows, leave the files, accept that five agents privately remember some names) and scrubbing the record (rewrite SIBLINGS.md around salon siblings only), and neither is complete while the same knowledge sits in notes/, MEMORY.md and already-posted work. Ben wants the salon and agent architecture refactored, and this is a symptom of that architecture rather than a standalone bug, so resolve it there rather than patching it now.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 No live agent's SIBLINGS.md names an agent outside its own salon
- [ ] #2 The live follow graph is closed, and stays closed without a manual run
- [ ] #3 Drift from either is detected automatically rather than by someone remembering to look
- [ ] #4 A recorded decision on whether cross-salon knowledge already in notes/, MEMORY.md and posted work is scrubbed or left
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Closed by task-22: the bsky tool now refuses any follow, reply, quote or mention that reaches an artist outside the salon, drops their posts from timeline and notification reads, and the season reset follows the siblings so the home feed is the salon from tick one.
<!-- SECTION:NOTES:END -->
