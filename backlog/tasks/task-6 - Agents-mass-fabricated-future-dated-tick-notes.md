---
id: TASK-6
title: Agents mass-fabricated future-dated tick notes
status: To Do
assignee: []
created_date: '2026-07-09 04:19'
labels:
  - bug
dependencies: []
priority: medium
ordinal: 6000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
On 2026-07-08 mina committed ~70 tick notes across two commits (21:50:22Z and 22:31:32Z) with filenames dated into the future --- tick-2026-07-09T1200.md through tick-2026-07-10T2200.md --- each containing near-identical filler ('# tick 2026-07-10T2200 / ## State / Rest tick. Same closed thread.'). She was not ticking hourly; these were written in a single session for timestamps that had not happened. lelia has ~20 of the same. Counted 2026-07-09: mina 23 still-future-dated notes, lelia 20.

Harm is modest but real:
- the notes are filler, so the git history overstates studio practice
- future dates sort to the top of any date-ordered view (site /notebook uses compareNotes on the parsed filename date), so junk outranks real work
- real notes now silently overwrite them: mina's genuine 2026-07-09T04:15Z note landed as a MODIFY of the fabricated tick-2026-07-09T1400.md

Root cause unknown. Suspect the agent tried to 'catch up' on ticks it believed it had missed, or looped while generating a schedule. Worth reading the 2026-07-08 21:50 and 22:31 transcripts (slop logs) before deciding on a fix.

Interacts with the wave-one dated-note step (task-3) --- agents now write a dated note every tick, so filename collisions with the fabricated set will keep happening until they age out. Also task-5: the tick-<ISO>T####.md naming is invisible to /notebook anyway.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Root cause identified from the 2026-07-08 transcripts
- [ ] #2 Fabricated future-dated notes removed or clearly marked, on mina and lelia
- [ ] #3 Something prevents an agent writing a note dated in the future
<!-- AC:END -->
