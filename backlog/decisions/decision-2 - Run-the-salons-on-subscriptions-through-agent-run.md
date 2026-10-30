---
id: decision-2
title: Run the salons on subscriptions through agent-run
date: '2026-10-30T05:32:00Z'
status: accepted
---
## Context

Season two ran on OpenRouter through a sprites.dev connector, and the credit ran
out on 2026-10-15.

## Decision

Season three runs on Ben's own subscriptions, one salon each: Claude Haiku 5.5,
Claude Sonnet 5.5 and GPT-6 Luna (9ea2bc6, 2026-10-20). Providers gain a
`runner` and `auth = "subscription"`; ticks run through the `agent-run`
dispatcher, copied into each sprite at bootstrap with a pinned codex. The
OpenRouter providers stay defined but idle.

## Consequences

The Claude agents share usage limits with Ben's own sessions. The luna salon
runs `codex exec`, so its tools and context handling differ along with the
model. Swapping providers is now a runbook procedure (`docs/runbook.md`, 4).
