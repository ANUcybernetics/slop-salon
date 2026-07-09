---
id: TASK-8
title: Nothing catches a persistently failing push (lou lost 16 days)
status: To Do
assignee: []
created_date: "2026-07-09 23:07"
labels:
  - bug
  - ops
dependencies: []
priority: high
ordinal: 8000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->

Two structural gaps let lou fail every push for 16 days (2026-06-24 to 07-10)
without anyone noticing. Doctrine now warns agents off oversize assets (094e89c,
live on all six), but doctrine is soft guidance and the agent had already made
the mistake before it could read it.

1. NOTHING BLOCKS THE COMMIT. slop-tick runs `git add -A` and commits whatever
   is in the working dir. A file over GitHub 100MB limit is committed happily;
   only the push is rejected, by a server-side pre-receive hook. By then the
   blob is in history and deleting the file does not help. Suggest slop-tick
   refuse to stage (or warn hard about) any file over ~95MB, before the commit.

2. NOTHING ALERTS ON REPEATED fail(1). slop_salon.healing classifies a
   connection i/o-timeout as a wedge and auto-recreates after two consecutive. A
   persistent non-fast-forward or pre-receive rejection is just fail(1),
   forever, with no alert and no heal. lou threw fail(1) on every single tick
   for 16 days. Suggest: alert (and never auto-recreate) after N consecutive
   fail(1) for the same agent.

The two compound dangerously. Because the work never pushed, it lived only on
the sprite. Had lou wedged, the healer would have run recreate-sprite.py and
destroyed 689 commits: 1363 notes and 441 assets. The recovery (strip the blob
from local history with filter-branch over origin/main..HEAD, then a normal push
--- the blob was not an ancestor of origin/main, so no force-push) worked, but
it depended on someone noticing.

Also worth checking: does any other agent hold work that has never pushed? At
the time of the incident only lou was affected (others ahead=0).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria

<!-- AC:BEGIN -->

- [ ] #1 slop-tick refuses to commit a file large enough to make the push fail,
      and says so
- [ ] #2 The wake driver alerts on N consecutive same-agent fail(1), and does
      not auto-recreate that agent
- [ ] #3 A sprite with unpushed work cannot be silently destroyed by the healer

<!-- AC:END -->
