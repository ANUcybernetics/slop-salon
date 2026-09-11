---
id: TASK-20
title: Report the DeepSeek prompt-caching cap to OpenRouter
status: To Do
assignee: []
created_date: '2026-09-11 02:40'
labels:
  - providers
  - cost
dependencies: []
priority: medium
ordinal: 20000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Every DeepSeek model reachable through OpenRouter's Anthropic endpoint caches at most ~3328 prompt tokens per Claude Code request, however large the prompt, so each tick re-pays for its whole prefix. Production hit rates are 7-8% against 92-96% for the GLM and Muse Spark salons. The deepseek salon has been moved to the cheaper vision model to contain the cost, but the cap itself is unresolved and caps how cheap that salon can ever be. The evidence, the A/B that isolates it, and the channel to use are written up in docs/openrouter-cache-report.md.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Report posted in the #help forum at discord.gg/openrouter
- [ ] #2 Any OpenRouter response recorded in docs/openrouter-cache-report.md
- [ ] #3 If unanswered, the same report is sent to DeepSeek, since which side owns the fault is undetermined
<!-- AC:END -->
