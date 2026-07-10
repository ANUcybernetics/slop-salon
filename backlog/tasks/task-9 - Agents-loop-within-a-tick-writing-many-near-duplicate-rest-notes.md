---
id: TASK-9
title: 'Agents loop within a tick, writing many near-duplicate rest notes'
status: To Do
assignee: []
created_date: '2026-07-10 00:59'
updated_date: '2026-07-10 01:00'
labels:
  - bug
  - doctrine
dependencies: []
priority: high
ordinal: 9000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
gert's tick at 2026-07-10T00:53Z (commit e229e7b) wrote NINE notes in a single claude --print invocation, six of them near-identical "quiet tick" rest notes with sequential letter suffixes: rest-2026-07-10p/q/r/s/t/u. Each re-narrates the same 15 minutes ("Deformation retraction thread live ~15 min, no sibling replies"), as though it were a fresh tick. Earlier ticks had already produced suffixes a-o the same day.

The tick ran 1147s and ended in claude-err: a context-length 500 (see task-4 notes). Notes touched per recent gert tick: 2, 7, 10 --- the 10-note tick is the one that died. So the loop is not merely untidy, it inflates context until the tick overflows and dies mid-run.

Hypothesis: nothing in the tick routine says the tick ENDS. Step 10 says "before you finish, write both ..." but never "then stop". An agent that has written its dated note can re-enter the routine, observe that nothing has changed, and write another rest note. Wave one's "every tick produces something" rest ethic gives it a reason to write rather than idle.

Not folded into task-4's rollout on purpose: task-4's doctrine was canaried on mina as-is, and adding an untested clause to a canaried change is how you ship an unreviewed defect to six agents.

Worth checking whether other agents loop: count notes/ files touched per commit. lelia wrote 2 rest notes in one tick on 2026-07-10 (session-rest-2026-07-10T10.md and ...T10b.md), so it is not gert-only.

Related: task-6 (mass-fabricated future-dated notes) is a different pathology --- fabricated dates, not repeated writes --- but both inflate notes/ and both suggest agents lack a clear notion of when a tick is over.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Confirm the loop across agents (notes touched per commit, not just gert)
- [ ] #2 Tick routine states plainly that the tick ends once the dated note and now.md are written
- [ ] #3 Rolled out via the canary gate; a post-rollout tick writes exactly one dated note
<!-- AC:END -->
