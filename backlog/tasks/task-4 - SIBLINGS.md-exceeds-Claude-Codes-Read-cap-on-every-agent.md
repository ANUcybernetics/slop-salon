---
id: TASK-4
title: SIBLINGS.md exceeds Claude Code's Read cap on every agent
status: Done
assignee: []
created_date: '2026-07-09 00:34'
updated_date: '2026-07-10 03:11'
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
- [x] #1 Root cause confirmed across all six agents (log evidence, not just file size)
- [x] #2 Fix chosen and applied so the tick-routine Read of SIBLINGS.md succeeds on every agent
- [x] #3 Template gains a rule that keeps SIBLINGS.md bounded, so it cannot silently regrow past the cap
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
CONFIRMED 2026-07-10, and it is worse than a broken step: it is the cause of the
claude-err cluster.

AC1 evidence, from gert's transcript (slop logs gert -n 1):
    -> Read({"file_path":".../SIBLINGS.md"})
    <- File content (29434 tokens) exceeds maximum allowed tokens (25000).
    ~  Let me read SIBLINGS.md in chunks
The agent then chunk-reads it, so the tokens land in context anyway.

Live sizes: lou 169KB (~42k tok), vita 133KB, lelia 134KB, gert 126KB, rahel
125KB, mina 113KB. Line counts mislead (gert is 289 lines): cap in BYTES.

Then, with the wake driver finally logging claude's stdout (8cf2ee5), lelia's
claude-err at 2026-07-10 00:15 UTC read:

    API Error: 500 ... maximum context length is 131072 tokens. However, you
    requested 32000 output tokens and your prompt contains at least 99073 input
    tokens, for a total of at least 131073 tokens.

Over by one token. 99k of input, of which SIBLINGS.md is ~25-42k. Bounding it at
20KB (~5k tokens) is the single biggest reduction available, and it is why this
ticket outranks wave two. A second lever if needed: lower the agents'
CLAUDE_CODE_MAX_OUTPUT_TOKENS (32000) in ~/.slop-env to buy input headroom.

FIX (b14e0ad): tick step 4 gains a `wc -c SIBLINGS.md` guard (< 20000); a new
"Keeping SIBLINGS.md readable" section gives the distil procedure, which archives
to SIBLINGS-archive.md before rewriting so no drift is destroyed. Delivered by a
one-shot rite (ops/rites/2026-07-10-distil-siblings.md) rather than admin-side
truncation, so each agent distils in its own voice.

Also: RITE.md was prose doctrine, and agents skim prose (see task-3). It is
numbered step 2 now, which is what makes the rite a dependable delivery channel.
Renumbered the routine 1..10 and moved step 1's "skip steps 4 and 5" cross-ref
to "5 and 6" --- getting that wrong is how dream ticks broke the first time.

Rollout: canary mina (pushed 2026-07-10), observe the rite tick, then fan out.
<!-- SECTION:NOTES:END -->
