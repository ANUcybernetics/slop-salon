---
id: TASK-13
title: Investigate fleet-wide context-overflow claude-errs (constant 99073 figure)
status: To Do
assignee: []
created_date: '2026-07-25 06:43'
labels:
  - ops
  - investigation
dependencies: []
priority: medium
ordinal: 13000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Every context-overflow claude-err in the journal reports byte-identical numbers: "requested 32000 output tokens and your prompt contains at least 99073 input tokens, for a total of at least 131073". Over the 14 days to 2026-07-25 that exact figure appears 106 times across five agents (all six have claude-errs: gert 35, vita 24, lou 24, lelia 21, mina 16, rahel 14 --- 134 total, ~10 lost ticks/day, ~3% of the fleet's ticks).

The constant is almost certainly not a real prompt size: 99073 = 131072 - 32000 + 1, i.e. the context window minus the requested output budget, plus one --- the minimum count that trips vLLM's check. So the error reports the threshold, not the prompt, and the earlier "a 99k-token prompt" diagnosis understates: actual prompts at failure are >= 99k and otherwise unknown.

Two threads to pull:

1. The 32000-token output request eats a quarter of the 131k window. If the in-sprite claude CLI's max output tokens can be lowered (e.g. CLAUDE_CODE_MAX_OUTPUT_TOKENS in ~/.slop-env), input headroom grows by the same amount --- likely the cheapest large win. Check what the pinned claude 2.1.92 actually sends and honours.
2. What drives prompts past ~99k mid-tick. Overflow ticks die late (mostly 1000--1700s runtimes), so this is context accumulated during long agentic sessions --- possibly large file reads or tool output, not the initial prompt. vLLM request logs on cybersonic (or a temporary logging bump) could show real prompt sizes near the failure point.

Related prior fix: SIBLINGS.md capping (the largest single contributor at the time) --- this is the residual.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The constant 99073 figure is confirmed (or refuted) as a threshold artifact of window minus max_tokens, with the reasoning recorded in this task
- [ ] #2 Real prompt sizes near failure are measured for at least one overflowing agent, identifying what fills the window mid-tick
- [ ] #3 A mitigation is chosen and rolled out fleet-wide (canary first per rollout doctrine), e.g. reduced max output tokens or in-tick context hygiene
- [ ] #4 Fleet claude-err rate over the following 7 days is measurably below the current ~10/day baseline
<!-- AC:END -->
