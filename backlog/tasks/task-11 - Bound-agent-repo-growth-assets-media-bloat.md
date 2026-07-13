---
id: TASK-11
title: Bound agent repo growth (assets/ media bloat)
status: Done
assignee:
  - '@claude'
created_date: '2026-07-13 06:38'
updated_date: '2026-07-13 12:24'
labels:
  - infra
  - ops
dependencies: []
priority: medium
ordinal: 11000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Agent GitHub repos have grown to 0.5-1.1 GB each (~5 GB fleet-wide; gert 1.17 GB) from committed media in assets/ --- video (mp4), audio (wav/mp3), images (webp/png) --- accumulated unpruned via each tick's `git add -A`. All notes/text together are ~1.3 MB, so it is entirely media. It is live retained assets, not history churn (current tree ~= repo size), so a history rewrite alone won't fix it; the retention policy has to change. This already broke the clone-based push tooling (worked around 2026-07-13 via the GitHub Contents API), makes in-sprite `git pull`/`gc` heavy every tick, and threatens recreate-sprite.py, which must move ~1 GB and can fail the same way a full clone does --- exactly when a heal is needed. Low-hanging waste: WAV and PPM are stored uncompressed.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A retention mechanism stops assets/ growing unboundedly, so each agent repo size stabilises well under 1 GB (e.g. a bounded-assets rite that keeps the last N days and drops/archives the rest, akin to the SIBLINGS.md cap)
- [x] #2 A decision is recorded on where large assets live --- bounded in-repo assets/, Git LFS, or an external store --- with the effect on the site's notebook loader (raw.githubusercontent) and on posted-media-on-Bluesky considered
- [x] #3 Existing bloat is reduced across all six repos, or a deliberate decision is recorded not to rewrite history
- [x] #4 A fresh clone and recreate-sprite.py both complete reliably within a reasonable time on the reduced repos
- [x] #5 Agents are steered away from committing uncompressed formats (WAV, PPM) --- prefer compressed audio/image encodings
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Follow-ups completed 2026-07-13 (same session):
- AC5 doctrine + WAV/PPM steer delivered to all six live agents via rite ops/rites/2026-07-13-assets-ephemeral.md. Each agent reworded its own (drifted) CLAUDE.md: removed the now-false "durable record is your repo" / 100 MB oversize-push warning / "outputs become part of the repo's record", added media-is-uncommitted + compressed-encoding preference. Verified fleet-wide: RITE.md gone, "100 MB" absent, "not committed" + compressed nudge present on all six.
- Root-level media loophole closed: templates/.gitignore now ignores media by extension (raster/audio/video globs), not just assets/. Pushed to all six.
- Canary discipline held throughout: mina canaried both the strip and the rite (each observed clean before fan-out).

Not done (deliberately): sprite-local .git left fat (unreferenced objects reclaim on next recreate; foreground gc risks the checkpoint-remount wedge). No AC needs it.
<!-- SECTION:NOTES:END -->
