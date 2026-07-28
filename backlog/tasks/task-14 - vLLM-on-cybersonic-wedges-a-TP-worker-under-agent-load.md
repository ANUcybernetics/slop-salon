---
id: TASK-14
title: vLLM on cybersonic wedges a TP worker under agent load
status: To Do
assignee: []
created_date: '2026-07-28 04:52'
updated_date: '2026-07-28 10:22'
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

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
PAUSED 2026-07-28 ~20:25 AEST (deliberate, admin-authorised). The crash-loop was
churning a shared GPU box --- 10 prober restarts --- so everything is stopped
rather than left thrashing:

  weddle:      systemctl --user stop slop-wake.timer slop-wake-watchdog.timer
  cybersonic:  systemctl --user stop cybersonic-vllm-health.timer
               systemctl --user stop cybersonic-vllm.service

All four units are STOPPED but still `enabled`, so this is a pause, not a
disable --- they will come back on their own if the user manager restarts (reboot
or re-login). Nothing is watching while paused: the dead-man check is one of the
things stopped, by design, so it does not file an hourly todo about a planned
outage. That means an unnoticed resume is the failure mode to watch for here.

Restore, in this order (prober last, so it cannot fight a cold start):
  cybersonic:  systemctl --user start cybersonic-vllm.service   # ~160-240s warmup
               curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8001/health
               systemctl --user start cybersonic-vllm-health.timer
  weddle:      systemctl --user start slop-wake.timer
               systemctl --user start slop-wake-watchdog.timer

Two findings from the shutdown itself:

- `systemctl stop` took the full TimeoutStopSec=120 and needed the cgroup
  SIGKILL. vLLM could not shut down on SIGTERM, which corroborates a genuinely
  hung TP worker rather than a clean crash --- and is why Restart=always never
  helped: the supervised process never exited.
- GPUs 0-3 released fully (1 MiB each). GPU 4 is now running ANOTHER user's vLLM
  (u9714433, Qwen2.5-14B-Instruct-AWQ, port 8004, ~21.9 GB); it was idle at
  15:09. So the 'move TP off GPU 2 onto GPU 4' bisect step is no longer free ---
  it would contend with that job. Re-check occupancy before trying it. Their
  presence on the same box is also an untested environmental variable for the
  worker hangs (PCIe/P2P or host-memory contention), not yet ruled in or out.
<!-- SECTION:NOTES:END -->
