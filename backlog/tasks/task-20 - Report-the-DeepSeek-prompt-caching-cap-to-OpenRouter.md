---
id: TASK-20
title: Report the DeepSeek prompt-caching cap to OpenRouter
status: To Do
assignee: []
created_date: '2026-09-11 02:40'
updated_date: '2026-09-20 04:55'
labels:
  - providers
  - cost
dependencies: []
priority: medium
ordinal: 20000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Every DeepSeek model reachable through OpenRouter's Anthropic endpoint caches a fixed-size prefix per Claude Code request and no more, however large the prompt, so each tick re-pays for the rest of it. The ceiling has moved once: ~3328 tokens when measured 2026-09-06, ~20.9k when re-measured 2026-09-20, with the shape of the fault unchanged. Hit rates went 7-8% to 31% on a 105k-token run, against 86% for GLM 5.3 Flash on the same harness and conversation. Claude Code also went 2.1.263 to 2.1.278 between the two, so the improvement cannot be attributed to either side. The deepseek salon has been moved to the cheaper vision model to contain the cost, but the cap itself is unresolved and still caps how cheap that salon can ever be. Both measurements, the A/B that isolates it, and the channel to use are written up in docs/openrouter-cache-report.md.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Report posted in the #help forum at discord.gg/openrouter
- [ ] #2 Any OpenRouter response recorded in docs/openrouter-cache-report.md
- [ ] #3 If unanswered, the same report is sent to DeepSeek, since which side owns the fault is undetermined
- [ ] #4 The DeepSeek-direct control is run once that account has balance (it returns 402 Insufficient Balance), since it is what separates OpenRouter's translation layer from DeepSeek's upstream
<!-- AC:END -->
