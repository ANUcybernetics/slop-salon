---
id: TASK-14
title: vLLM on cybersonic wedges a TP worker under agent load
status: To Do
assignee: []
created_date: '2026-07-28 04:52'
updated_date: '2026-07-28 22:13'
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
DIFFERENTIAL DIAGNOSIS (2026-07-29). Earlier notes listed a bisect order, not an
assessment of causes; this is the assessment. Symptom, precisely: one TP worker
stops computing while its peers spin at 100%, EngineCore's shm_broadcast dequeue
times out (VLLM_EXECUTE_MODEL_TIMEOUT_SECONDS=300, 'RPC call to sample_tokens
timed out'), and every in-flight tick dies with ECONNRESET.

REFUTED --- MTP speculative decoding. The 15:07 crash occurred with spec decode
confirmed off (launcher logged 'speculative decoding disabled';
spec_decoding_stats=None in the dump). Same signature as with it on. Left off
anyway (7fedb2d): it costs only generation speed and keeps the variable out.

REFUTED --- the second tenant on the box. Another user's vLLM (u9714433,
Qwen2.5-14B-AWQ, port 8004, ~21.9 GB on GPU 4) appeared between 15:09 and 20:20.
It cannot be the original cause: crashes at 13:14, 14:01 and 14:43 all predate it,
and at 15:09 GPU 4 read 1 MiB / 0%. Nor does it measurably aggravate: mean
inter-restart gap was ~30 min before it appeared and ~31 min after (full series in
minutes: 17.5, 42.0, 27.7, 17.5, 42.0, 17.5, 34.7, 34.7, 32.3, 17.5, 45.2, 34.8,
26.5).

REFUTED --- host memory or /dev/shm exhaustion, despite the failure being a
shm_broadcast stall. 503 GB RAM with 490 GB available; /dev/shm is 252 GB with
5.1 MB used.

NOT SUPPORTED BUT NOT RULED OUT --- PSU / power limit. Against it: HW Thermal
Slowdown violation counters are 0 us on all six GPUs (never a thermal emergency);
the mechanism does not match the symptom, since a power or thermal cap throttles
clocks --- making a GPU slower, not idle --- whereas the hung worker sat at 0%
utilisation for 6+ seconds while its peers held 100%; and a PSU trip would drop
the GPU off the bus and free its memory, while GPU 2 kept its full 22.2 GB shard.
For it: all six GPUs do hit their software power cap under load (SW Power Capping
counters nonzero, up to ~96 min cumulative), 4x350W for our TP group plus a
250W-capped tenant is a substantial draw, and GPUs 4 and 5 are capped to 250W
while 0-3 run at 350W --- which suggests power on this box has already been
managed by someone. UNRESOLVED because the decisive test is blocked: Xid messages
in the kernel log are the definitive discriminator between a hardware/power event
and a software hang, and the account is in `sudo` but not `adm`/
`systemd-journal`, so `sudo -n` fails and journalctl -k returns nothing. ONE
COMMAND WITH A PASSWORD SETTLES THIS: `sudo dmesg | grep -iE 'xid|nvrm|fallen
off the bus'`. Run it before spending more on a software bisect.

OPEN --- the experimental Mamba-mode prefix cache (--enable-prefix-caching on a
hybrid DeltaNet model). Now the leading software candidate. Expensive to give up
(the agent loop re-sends a growing shared prefix), so test after the Xid check.

OPEN --- the dev-nightly build (v0.21.1rc1.dev179+g5ecd8e9c7). A plain TP/shm bug
is entirely plausible at this vintage.

WEAK --- 'GPU 2 is faulty'. Recorded because it was measured, but it rests on ONE
hang: GPU 2 idle across three samples while 0/1/3 held 100%, with worker pid
27325 mapped to index 2. The first two hangs were not attributed --- I only
thought to look at the third. If TP2 is merely the rank that waits while another
rank strags, this points nowhere. Cheap fix: have the prober record per-GPU
utilisation before it restarts, so the next hang attributes itself.

TWO MEASUREMENT CAVEATS, both mine:
- The '~17-25 min between crashes' figure is partly an artefact of the prober
  itself. WARMUP_SEC=900 plus three probes at ~70s gives an ~18.5 min floor on
  the restart-to-restart gap, which is exactly the observed minimum of 17.5 min.
  So in the fast cases vLLM died at or before 15 minutes and detection was
  simply as early as possible; true survival time is unmeasured. Wakes also fire
  every 30 min, so crash cadence and load cadence are entangled.
- cybersonic-vllm-health.service sets TimeoutStartSec=2min, but a restart of
  vLLM can take 120s to stop plus a cold start --- so the prober can be
  SIGKILLed while doing the one thing it exists to do. Evidence: 14 'restarting'
  log lines against only 10 'restart issued' confirmations. The restarts still
  happened (systemd owns them once issued) but the log under-reports and the
  flock is dropped early. Raise TimeoutStartSec well above 120s.
<!-- SECTION:NOTES:END -->
