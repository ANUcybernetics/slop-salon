---
id: TASK-1
title: Verify sprites.py against a real sprite
status: Done
assignee: []
created_date: '2026-05-10 23:30'
labels:
  - provisioning
  - sprites
  - verification
dependencies: []
priority: high
ordinal: 1000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
src/slop_salon/sprites.py was written from spec, not against a live API --- SPRITES_BASE_URL and the three ENDPOINT_* paths are placeholders, and the request/response shapes in create_sprite/exec/get_status haven't been checked against the real sprites.dev API. A real (Fly-authed) sprite is also needed to verify a set of provisioning assumptions: docs say sprites ship with claude/gemini/codex pre-installed, so provision.py step 6 (curl claude.ai/install.sh) may be redundant; APT_PACKAGES (git, imagemagick, ffmpeg, sox, jq, curl, python3.14, nodejs) may overlap with the default image; sprite-level skills under /.sprite/ teach claude about the platform and we should know what's actually in there; persistence claims (filesystem survives between ticks, checkpoint/restore in ~1s) should be confirmed firsthand before they end up in agent-facing docs as fact.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Sign in to sprites.dev with the Fly-authed account and mint an API token
- [x] #2 SPRITES_BASE_URL and the three ENDPOINT_* constants in src/slop_salon/sprites.py match the real API
- [x] #3 create_sprite/exec/get_status request and response shapes match the real API (or sprites.py is patched to fit)
- [x] #4 List of what is pre-installed in the default sprite image is captured (in the design doc or runbook)
- [x] #5 Contents of /.sprite/ are reviewed; any agent-relevant capability not already covered in templates/CLAUDE.md is flagged
- [x] #6 provision.py is trimmed of any steps the sprite already does (e.g. installing claude, redundant apt packages)
- [x] #7 Persistence across sprite-stop / sprite-restart confirmed firsthand (apt-installed package and a scratch file both survive)
- [x] #8 Checkpoint create + restore round-trip verified
<!-- AC:END -->
