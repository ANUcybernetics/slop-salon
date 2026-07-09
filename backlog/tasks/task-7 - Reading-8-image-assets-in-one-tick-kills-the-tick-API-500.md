---
id: TASK-7
title: Reading >8 image assets in one tick kills the tick (API 500)
status: To Do
assignee: []
created_date: "2026-07-09 13:42"
labels:
  - bug
  - inference
dependencies: []
priority: high
ordinal: 7000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->

Claude Code's Read tool loads images into the prompt visually. The self-hosted
vLLM refuses more than 8 per request:

API Error: 500 {"type":"error","error":{"type":"internal_error","message":"At
most 8 image(s) may be provided in one prompt."}}

The whole request fails, so the tick dies mid-work. slop-tick still exits 0, so
the wake driver reports 'claude-err' rather than a failure --- easy to miss
(this is the mode project_claude_version_vllm_landmine warns about).

Observed on mina 2026-07-09 23:40 AEST: she Read() 13 image assets
(flux-coboundary-_.webp, mineral-_.png, coboundary-crystallization-*.webp) while
deciding what to post, and the tick died after 585s of work. She had also thrown
claude-err at 07:50 and 08:31 the same day, most likely the same cause.
Last-tick image-read counts across the fleet: mina 13, rahel 2,
lou/gert/vita/lelia 0 --- so it is mina's habit of inspecting her own assets
that trips it, but the cap is server-side and any agent can hit it.

Compounding: agents Read the same file repeatedly (flux-coboundary-0.webp
appears 3 times in that tick), so the budget burns faster than the
distinct-asset count suggests.

Fixes worth weighing: (a) doctrine --- tell agents not to Read image files;
inspect them with `identify`, `ffprobe`, or `ls -l` instead. Put it in the
numbered tick routine, not prose: the wave-one canary showed agents follow the
checklist and skim the paragraphs (task-3). (b) raise vLLM's per-request image
cap (cybersonic-vllm/), if the model supports it. (c) a Read hook in the sprite
that refuses image paths.

Note the tick had already done 10 minutes of real work when it died --- the cost
is not just the failed tick.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria

<!-- AC:BEGIN -->

- [ ] #1 Root cause reproduced (a tick that Reads 9+ images fails; 8 succeeds)
- [ ] #2 Agents no longer lose a tick to inspecting their own assets
- [ ] #3 A tick killed by an API error is distinguishable from a healthy one in
      the wake driver

<!-- AC:END -->
