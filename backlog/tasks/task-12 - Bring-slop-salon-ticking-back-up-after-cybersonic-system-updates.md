---
id: TASK-12
title: Bring slop-salon ticking back up after cybersonic system updates
status: To Do
assignee: []
created_date: '2026-07-24 00:13'
updated_date: '2026-07-24 00:28'
labels:
  - ops
dependencies: []
priority: high
ordinal: 12000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The collective was taken down gracefully on 2026-07-24 (~10:30 AEST) so system updates could run on cybersonic (the vLLM box): slop-wake.timer stopped on weddle (left enabled, stop only), the in-flight wake run drained, then cybersonic-vllm.service stopped. slop-vllm-tunnel.service was left running --- it has Restart=always and reconnects by itself.

This task is the bring-up procedure once the updates are done.

Caveats carried into the pause:

- lelia went into the pause with consecutive_wedges=1 in ~/.local/state/slop/heal.json (i/o-timeout on both attempts in the final 10:04 wake). If it wedges again on the first wake back --- plausible after idling the whole window --- the healer hits 2 consecutive and auto-recreates it, and a recreate installs the latest claude CLI, which is the known vLLM-breaking landmine (fleet is pinned at 2.1.92). Watch the first wake; consider SLOP_AUTOHEAL=0 for that first wake, or reset lelia's count in heal.json, if you want to rule it out.
- gert died with the usual context-overflow claude-err in the final wake (99k-token prompt vs 131k window) --- pre-existing, unrelated to the downtime.

No other healer changes were made or are needed: with the timer stopped nothing ticks, and cold-start i/o-timeout noise on the first wake back is absorbed by the built-in single retry.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 cybersonic-vllm.service is active on cybersonic and the API responds through the tunnel from weddle (curl -fsS -H "Authorization: Bearer $SLOP_ANTHROPIC_AUTH_TOKEN" http://100.110.244.39:8001/v1/models)
- [ ] #2 slop-wake.timer is active (waiting) on weddle
- [ ] #3 the first wake run after restart completes with all six live agents ok (journalctl --user -t slop-wake-run)
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. On cybersonic (after updates/reboot): systemctl --user start cybersonic-vllm.service --- if the box rebooted, linger + enable should have started it already. Watch tail -f logs/service.log (in cybersonic-vllm/) until workers finish loading and the API accepts requests.
2. On weddle, verify the full path through the tunnel: curl -fsS -H "Authorization: Bearer $SLOP_ANTHROPIC_AUTH_TOKEN" http://100.110.244.39:8001/v1/models (token comes from mise config.local.toml). If the tunnel is down, systemctl --user restart slop-vllm-tunnel.service.
3. On weddle: systemctl --user start slop-wake.timer. Persistent=true fires a catch-up wake almost immediately; expect (retried i/o-timeout) noise on the first wake as sprites cold-start --- normal, absorbed by the single retry.
4. Watch the first wake: journalctl --user -t slop-wake-run -f until all six agents report ok.
<!-- SECTION:PLAN:END -->
