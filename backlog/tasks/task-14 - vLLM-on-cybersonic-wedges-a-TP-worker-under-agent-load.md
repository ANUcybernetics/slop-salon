---
id: TASK-14
title: vLLM on cybersonic wedges a TP worker under agent load
status: To Do
assignee: []
created_date: '2026-07-28 04:52'
labels: []
dependencies: []
ordinal: 14000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
vLLM's EngineCore dies every 20-30 min under the collective's tick load: a TP worker stops answering, EngineCore hits a shm-broadcast TimeoutError in multiproc_executor.get_response, and every in-flight tick dies with ECONNRESET. Three occurrences in 90 min on 2026-07-28 (13:14, ~14:01/14:17, 14:40).

Not memory pressure (kv_cache_usage 0.14-0.18) and not contention past the documented cap (the second crash ran 4 concurrent requests, exactly WAKE_CONCURRENCY). Both captured dumps show ~31k computed tokens per request and 1000+ output tokens, i.e. it fails deep into long generations.

The crash never names a kernel, so logs cannot single out which experimental feature is at fault. Three candidates, to be bisected in cost order:
1. MTP speculative decoding --- DISABLED 2026-07-28 (7fedb2d), first bisect step
2. --enable-prefix-caching, vLLM's experimental Mamba-mode path for DeltaNet layers --- expensive to lose, the agent loop re-sends a growing shared prefix each turn
3. the build itself: v0.21.1rc1.dev179+g5ecd8e9c7, a dev nightly

Mitigated but not fixed: cybersonic-vllm-health.timer now restarts a hung vLLM within ~3 min (262273f), so an occurrence costs a few minutes rather than hours. Ticks spanning a crash are still lost.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Fleet completes several consecutive wakes with no claude-err attributable to ECONNRESET
- [ ] #2 Root cause identified among the three candidates, or ruled out and documented
- [ ] #3 cybersonic-vllm/README.md records the finding and the final config
<!-- AC:END -->
