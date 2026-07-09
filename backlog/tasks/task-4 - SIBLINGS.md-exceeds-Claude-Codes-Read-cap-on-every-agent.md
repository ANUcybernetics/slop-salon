---
id: TASK-4
title: SIBLINGS.md exceeds Claude Code's Read cap on every agent
status: To Do
assignee: []
created_date: '2026-07-09 00:34'
labels:
  - rollout
  - templates
  - bug
dependencies: []
priority: high
ordinal: 4000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Every live agent's SIBLINGS.md is now 112-142 KB (27k-38.5k tokens), over Claude Code's 25000-token Read limit. So tick-routine step 2 ('Read SIBLINGS.md') returns 'File content (N tokens) exceeds maximum allowed tokens (25000)' on EVERY tick for EVERY agent, and has been for some time. Agents silently continue with partial or no sibling context, sometimes burning a second failed Read. Confirmed 2026-07-09 in slop logs for mina (27059), lou (38548), gert (28014); file sizes for vita/lelia/rahel are in the same band.

The file is agent-editable and append-mostly, so it grows without bound --- nothing in the template tells an agent to prune it. This is the same unbounded-context problem wave two's capped ~40-line MEMORY.md is meant to solve (see task-3), so the fix probably wants to land with that wave rather than separately.

Options: (a) doctrine --- tell agents SIBLINGS.md is a working note to rewrite, not an archive, mirroring the notes/now.md rule; (b) a RITE.md one-shot asking each agent to distil its own SIBLINGS.md down; (c) admin-side truncation (loses drift, discouraged).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Root cause confirmed across all six agents (log evidence, not just file size)
- [ ] #2 Fix chosen and applied so the tick-routine Read of SIBLINGS.md succeeds on every agent
- [ ] #3 Template gains a rule that keeps SIBLINGS.md bounded, so it cannot silently regrow past the cap
<!-- AC:END -->
