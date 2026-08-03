---
id: TASK-16
title: 'Option: run the agents on a Claude Pro subscription via claude -p'
status: To Do
assignee: []
created_date: '2026-07-28 10:26'
updated_date: '2026-08-03 23:03'
labels: []
dependencies: []
ordinal: 16000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Assessment of moving the sprites off self-hosted vLLM onto Ben's Claude Pro
subscription, keeping the existing `claude --print` loop. Written up 2026-07-28
so the reasoning survives; NOT recommended as-is at the current tick cadence ---
see 'Why it does not fit' below.

HOW IT WOULD WORK. The plumbing is genuinely small, and that is the seductive
part. slop-tick already runs `claude --print "$PROMPT"` with no --model flag;
its own comment says the model and endpoint come from the ANTHROPIC_* vars in
~/.slop-env. Those four vars (ANTHROPIC_BASE_URL, _AUTH_TOKEN, _MODEL,
API_TIMEOUT_MS) are the ENTIRE coupling to vLLM. Claude Code resolves credentials
as ANTHROPIC_API_KEY -> ANTHROPIC_AUTH_TOKEN -> an OAuth profile on disk, so with
the first two unset it falls through to subscription auth. On Linux that profile
is ~/.claude/.credentials.json (mode 600). Provisioning writes ~/.slop-env from
admin SLOP_* vars with the prefix stripped (provision.py:60), so dropping the
three SLOP_ANTHROPIC_* entries admin-side is the change. Nothing in the tick
routine, the tools, or the templates moves.

Bonus either way (also true of the API-key path): leaving vLLM retires the
claude-version pin landmine. The fleet is held at 2.1.92 because 2.1.168 sends
Skills as a system-role message that vLLM 400s --- that cost lelia 3.5 days once
and re-arms on every recreate/provision.

WHY IT DOES NOT FIT --- the measured load. From the corrected tally (see the
usage double-count fix, c412ce0 --- the pre-fix numbers were 3.2x too high):

  ~14 API calls per tick, ~816k input tokens per tick
  ~45 ticks/agent/day x 6 agents = ~270 ticks/day
  => ~3,800 agentic API calls and ~220M input tokens per day, unattended

A consumer subscription is sized for one person working interactively. This is
two-plus orders of magnitude past that, so Pro is not a close call --- it is not a
rate-limit-tuning problem. Max 20x is arguable rather than absurd, but six 24/7
agents would still be a stretch and the failure mode is throttling mid-tick.

THREE BLOCKERS, worst first:
1. Rate limits, as above. Decisive.
2. Credential sharing across six machines. One profile copied to six sprites, each
   refreshing independently; OAuth refresh tokens typically rotate on use, so they
   may invalidate each other and silently deauthenticate the fleet. UNTESTED --- a
   canary would settle it.
3. Terms. A consumer subscription is for individual interactive use; unattended
   automation across six VMs is what API access is for. The risk is account-level,
   not agent-level, which is a different blast radius from a cost overrun.

CADENCE IS THE REAL VARIABLE. Subscription viability is a function of tick rate,
and tick rate is a knob we control. At 30-minute ticks this is hopeless; at a few
ticks per agent per day the arithmetic changes shape. Where it actually breaks
even is worth measuring rather than guessing --- and cutting cadence has
independent merit given tick cost, so this is not a wasted question.

THE HONEST ALTERNATIVE. An API key needs the IDENTICAL one-line env change and
carries none of the three blockers. Costed from the same measured basis:
~$17-20k/month on Sonnet at list, uncached; roughly $3-4k/month with prompt
caching actually applied (the ~30k prefix is identical across a tick's calls, and
a 1-hour TTL spans the 30-min gap between ticks); ~$1-1.5k/month on Haiku 4.5.
Note vLLM reports NO cache fields at all, so we currently have zero visibility
into cache behaviour --- moving to the real API would finally show it. Pinning a
cheap model is also an API-only lever: subscription auth gives whatever Claude
Code defaults to, so Haiku-tier economics are not available that way.

IF SOMEONE WANTS TO TEST IT ANYWAY, the canary is cheap (~20 min): pick one warm
agent, clear its three ANTHROPIC_* vars from ~/.slop-env, drop the credentials
file in, run a few natural ticks, and watch two things --- limit errors, and
whether a second sprite refreshing the same profile breaks the first. That
answers blockers 1 and 2 without touching the other five agents.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Decision recorded: subscription, API key, or stay on vLLM --- with the reason
- [ ] #2 If subscription is pursued: single-agent canary run, with limit errors and refresh-token behaviour observed across two sprites
- [ ] #3 If API key is pursued: spend cap set before the first tick, and cache-hit rate confirmed from real usage rather than estimated
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
2026-08-04: superseded in mechanism, not in conclusion. The provider abstraction
landed (see CLAUDE.md "Providers"), so this is no longer a one-off assessment ---
subscription auth is now one registry entry among four, selectable per agent with
`slop provider set`.

What survives from the assessment: the arithmetic still says Pro is hopeless at
30-minute ticks, and the three blockers still stand. Blocker 2 (shared OAuth
across six sprites) remains untested, and `slop provider set` now refuses to put
more than one agent on a subscription provider at once so that a canary has to
answer it before a fan-out can happen.

What changed: the "honest alternative" is no longer only the Anthropic API.
DeepSeek V4-Flash speaks Anthropic wire format at api.deepseek.com/anthropic, so
it needs the identical one-line change and costs ~$0.14/M input on a cache miss,
~$0.0028/M on a hit --- roughly $30/day uncached at the measured ~220M
input-tokens/day, and much less once caching applies. That is the default
fallback while cybersonic is down, and it also gives us the cache visibility vLLM
never reported.

Also: codex's session records carry `rate_limits.primary.used_percent` and
`plan_type`, which `slop usage` now surfaces. Blocker 1 becomes something to
measure on a canary rather than argue from token arithmetic.
<!-- SECTION:NOTES:END -->
