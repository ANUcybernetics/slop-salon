---
id: TASK-11
title: Bound agent repo growth (assets/ media bloat)
status: In Progress
assignee:
  - '@claude'
created_date: '2026-07-13 06:38'
updated_date: '2026-07-13 11:34'
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
- [ ] #5 Agents are steered away from committing uncompressed formats (WAV, PPM) --- prefer compressed audio/image encodings
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Resolved 2026-07-13. Decision: assets/ is an ephemeral cache, not an archive (media is not the durable copy of anything --- posted work is a Bluesky blob, the site reads only notes/).

- AC1 retention: templates/.gitignore ignores assets/ (passive, no per-tick agent compliance). Live on all six; growth halted. Verified in-sprite via git check-ignore.
- AC2 decision recorded in CLAUDE.md (architecture), docs/runbook.md, and memory.
- AC3 existing bloat: one-time git filter-repo rewrite (ops/strip-assets.py) force-pushed all six. Fleet .git ~5.1 GB -> ~28 MB (mina 619->3, vita 872->8.5, lou 948->4.9, rahel/gert 1.1GB->~4, lelia 490->2.6, all MB).
- AC4 verified: fresh clone of every repo now 5-6s with a 2.7-8.9M .git, zero assets (the recreate-sprite.py path).

Migration notes: strip resets sprites onto rewritten history out of band (never a rite) because slop-tick's git pull --rebase would replay pre-rewrite commits. Pre-flight refuses on a running tick or un-pushed commits (lelia had 1 stranded session note --- pushed it, no loss, then re-stripped). Fixed a pre-flight pgrep self-match bug mid-migration.

Follow-ups (not blocking): (a) AC5 WAV/PPM steer is in the template CLAUDE.md but not yet on live agents' drifted CLAUDE.md --- rolls out with the doctrine reword. (b) assets/-only ignore misses stray root-level media some agents commit (negligible today); could extend to ignore media by extension. (c) sprite-local .git stays fat (unreferenced objects) until next recreate; not gc'd to avoid the checkpoint-remount wedge.
<!-- SECTION:NOTES:END -->
