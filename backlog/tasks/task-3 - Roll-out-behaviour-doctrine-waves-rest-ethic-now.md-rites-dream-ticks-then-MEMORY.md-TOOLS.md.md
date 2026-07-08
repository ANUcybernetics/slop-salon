---
id: TASK-3
title: >-
  Roll out behaviour-doctrine waves (rest ethic, now.md, rites, dream ticks;
  then MEMORY.md + TOOLS.md)
status: To Do
assignee: []
created_date: '2026-07-08 22:51'
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
- [ ] #1 Wave-one template is live in mina's repo, with her pre-push CLAUDE.md drift reviewed (slop drift mina) and deliberately preserved or merged
- [ ] #2 Mina observed over multiple natural ticks, including at least one 03:00-05:00 Canberra window: now.md is being maintained, dream-tick behaviour is sane, no new tick failures
- [ ] #3 Wave one fanned out to the other five live agents, each with drift reviewed before push
- [ ] #4 Wave two drafted and rolled out (same canary gate): capped ~40-line MEMORY.md with @MEMORY.md import, TOOLS.md template stub, existing agents seeded via the first RITE.md push
- [ ] #5 Admin CLAUDE.md tunables/architecture notes and project memory updated to reflect what is live
<!-- AC:END -->
