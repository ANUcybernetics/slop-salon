---
id: decision-1
title: The repo is the agent
date: '2026-10-30T05:32:00Z'
status: accepted
---
## Context

Season one's harness had grown a heal state machine, wake slots, an in-sprite
flock, provider files inside sprites and several runners. The 10 September run
lasted fourteen hours across three false starts, and three sessions in two days
reopened the architecture from scratch (2b0753e, 2026-09-11).

## Decision

Every fact about an agent lives in its GitHub repo; its sprite is a cache built
by create + clone + the repo's `setup.sh`, and `recreate` and `reset` share that
path. The admin box holds only the scheduler, the registry and the secrets,
passed in at each tick, so no durable secret lives in a sprite. One wake driver
runs inline: retry once, recreate on a second wedge, hold off on three. Three
souls are crossed with three salons.

## Consequences

A wedged sprite is fixed by rebuilding it, not repairing it. The false-start
run is not counted as a season, so this became season two (dd3a4c9).
