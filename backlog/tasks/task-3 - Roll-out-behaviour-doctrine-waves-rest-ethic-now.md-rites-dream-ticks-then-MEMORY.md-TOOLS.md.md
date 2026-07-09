---
id: TASK-3
title: >-
  Roll out behaviour-doctrine waves (rest ethic, now.md, rites, dream ticks;
  then MEMORY.md + TOOLS.md)
status: In Progress
assignee: []
created_date: '2026-07-08 22:51'
updated_date: '2026-07-09 00:07'
labels:
  - rollout
  - templates
dependencies: []
priority: medium
ordinal: 3000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Wave one of the OpenClaw/Hermes-inspired doctrine changes is committed to templates/CLAUDE.md (bfd24c1..e0696bb, 2026-07-09): every-tick-produces-something rest ethic, notes/now.md intent letter, the RITE.md one-shot rite convention, and clock-keyed dream ticks (03:00-05:00 Canberra). It now needs the standard canary-then-observe rollout: mina first, an explicit multi-tick observation gate (including an overnight dream window), then fan-out. Wave two (capped ~40-line MEMORY.md with @MEMORY.md import, plus TOOLS.md seeded on existing agents via the first rite) is agreed but undrafted, gated on wave-one observations. NB: push-template.py overwrites an agent's own CLAUDE.md edits --- review drift before each push and fold it back in deliberately. Plan details in the project memory note project_behaviour_waves.md.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Wave-one template is live in mina's repo, with her pre-push CLAUDE.md drift reviewed (slop drift mina) and deliberately preserved or merged
- [ ] #2 Mina observed over multiple natural ticks, including at least one 03:00-05:00 Canberra window: now.md is being maintained, dream-tick behaviour is sane, no new tick failures
- [ ] #3 Wave one fanned out to the other five live agents, each with drift reviewed before push
- [ ] #4 Wave two drafted and rolled out (same canary gate): capped ~40-line MEMORY.md with @MEMORY.md import, TOOLS.md template stub, existing agents seeded via the first RITE.md push
- [ ] #5 Admin CLAUDE.md tunables/architecture notes and project memory updated to reflect what is live
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
2026-07-09: AC1 done. Wave one live on mina (repo commit 'Sync CLAUDE.md from admin templates (wave-one doctrine; mina's replicate/code paragraph preserved)').

Pushed a HAND-MERGED file, not push-template.py: mina had one genuine self-edit (a paragraph arguing code-based making is co-primary with replicate, from her cobweb/Feigenbaum work). Ben chose to preserve it. Method: diff live CLAUDE.md against the blob left by the last 'Ben Swift' sync commit (2026-06-07) to separate her edits from admin-side reflow noise, splice hers into the fresh render, push that. The rest of 'slop drift' output is cosmetic --- the template was rewrapped to 80 cols after the last sync.

The push also delivered the video-cap paragraph, which had never reached any agent (tool guard did; doctrine text didn't).

AC2 (observation gate) now open. Mina ticks ~every 30 min and was healthy pre-push. Next dream window: 03:00-05:00 Canberra, i.e. overnight 2026-07-09/10. Check after that: notes/now.md exists and is rewritten (not appended) across ticks; a dream entry appeared in notes/ with no posting during the window; no new tick failures.

Do NOT fan out (AC3) until that window has passed. All five remaining agents also have 1-3 self-edits since 2026-06-07 --- each needs the same isolate-and-merge treatment.

Known tension to watch: tick-routine step 6 and the studio cue still nudge mina toward replicate, which cuts against the paragraph she kept.
<!-- SECTION:NOTES:END -->
