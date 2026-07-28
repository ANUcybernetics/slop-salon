---
id: TASK-15
title: Resume slop-salon after the 2026-07-28 deliberate pause
status: To Do
assignee: []
created_date: '2026-07-28 10:25'
labels: []
dependencies: []
ordinal: 15000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The collective is intentionally idle. Four units are STOPPED but still `enabled`
as of 2026-07-28 ~20:25 AEST; the fleet has produced nothing since the 09:33
wake.

  weddle:      slop-wake.timer, slop-wake-watchdog.timer
  cybersonic:  cybersonic-vllm.service, cybersonic-vllm-health.timer

Why: vLLM wedged a TP worker every ~17-25 min under agent load and the health
prober restarted it 10 times in an afternoon. Every tick in that window died with
ECONNRESET, so the loop was burning a shared School GPU box to produce nothing.
Diagnosis and bisect state: task-14.

READ THIS BEFORE RESTARTING. Restoring as-is will resume the crash loop --- the
root cause is unresolved. Decide the inference path first:
  (a) continue the task-14 bisect (next lever: --enable-prefix-caching; the
      'move TP off GPU 2 onto GPU 4' option is no longer free, another user's
      vLLM occupies GPU 4 as of 20:20), or
  (b) point the sprites at the Anthropic API instead. Coupling is four env vars
      in each ~/.slop-env (ANTHROPIC_BASE_URL, _AUTH_TOKEN, _MODEL,
      API_TIMEOUT_MS); slop-tick passes no --model, so clearing them is the
      whole change. Measured cost basis: ~816k real input tokens/tick, ~14 API
      calls/tick, ~45 ticks/agent/day.

Restore order --- prober LAST, so it cannot fight a cold start:

  # cybersonic
  systemctl --user start cybersonic-vllm.service
  # cold start serves nothing for ~160-240s; wait for 200 before continuing
  curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8001/health
  systemctl --user start cybersonic-vllm-health.timer

  # weddle
  systemctl --user start slop-wake.timer
  systemctl --user start slop-wake-watchdog.timer
  mise exec -- uv run slop wake-check    # expect exit 0

Then watch one full wake before walking away: `journalctl --user -t
slop-wake-run -f`. A healthy wake is six `ok` lines; `claude-err` with
ECONNRESET means vLLM is wedging again --- stop rather than let it loop.

Also pending, blocked on a stable inference path: three agent-facing fixes are
committed but NOT deployed to any sprite --- the usage double-count fix (c412ce0,
runs in-sprite as slop-usage), the flattened bsky reads (6ec9501), and the
AskUserQuestion denial plus the CLAUDE.md tick-routine change (462364f). Roll
them out through the usual canary-then-observe gate once ticks are reliable, not
before: a canary cannot be read while every tick is failing for unrelated
reasons.

Gotcha worth knowing: the units are stopped, not disabled, so a reboot or
re-login on either box brings all four back automatically --- ticks resume
against whatever state vLLM is in, and the watchdog starts alerting again. While
paused, nothing is watching by design (the dead-man check is one of the stopped
units), so an unnoticed resume is the failure mode here, not an unnoticed
outage.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Inference path decided: vLLM stable across 3+ consecutive wakes, or sprites moved off it
- [ ] #2 All four units running again and 'slop wake-check' exits 0
- [ ] #3 One full wake observed green (six ok lines) before leaving it unattended
- [ ] #4 The three pending fixes rolled out to all six agents, or explicitly deferred with a reason
<!-- AC:END -->
