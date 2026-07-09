---
id: TASK-3
title: >-
  Roll out behaviour-doctrine waves (rest ethic, now.md, rites, dream ticks;
  then MEMORY.md + TOOLS.md)
status: In Progress
assignee: []
created_date: '2026-07-08 22:51'
updated_date: '2026-07-09 02:23'
labels:
  - rollout
  - templates
dependencies: []
priority: medium
ordinal: 3000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Wave one of the OpenClaw/Hermes-inspired doctrine changes is committed to templates/CLAUDE.md (bfd24c1..e0696bb, 2026-07-09): every-tick-produces-something rest ethic, notes/now.md intent letter, the RITE.md one-shot rite convention, and clock-keyed dream ticks (03:00-05:00 Canberra). It now needs the standard canary-then-observe rollout: mina first, an explicit multi-tick observation gate (including an overnight dream window), then fan-out. Wave two (capped ~40-line MEMORY.md with @MEMORY.md import, plus TOOLS.md seeded on existing agents via the first rite) is agreed but undrafted, gated on wave-one observations. NB: push-template.py overwrites an agent's own CLAUDE.md edits --- review drift before each push and fold it back in deliberately. Plan details in the project memory note project_behaviour_waves.md.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Wave-one template is live in mina's repo, with her pre-push CLAUDE.md drift reviewed (slop drift mina) and deliberately preserved or merged
- [ ] #2 Mina observed over multiple natural ticks, including at least one 03:00-05:00 Canberra window: now.md is being maintained, dream-tick behaviour is sane, no new tick failures
- [ ] #3 Wave one fanned out to the other five live agents, each with drift reviewed before push
- [ ] #4 Wave two drafted and rolled out (same canary gate): capped ~40-line MEMORY.md with @MEMORY.md import, TOOLS.md template stub, existing agents seeded via the first RITE.md push
- [ ] #5 Admin CLAUDE.md tunables/architecture notes and project memory updated to reflect what is live
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
--------------------------------------------------
--------------------------------------------------
--------------------------------------------------
2026-07-09: AC1 done. Wave one live on mina (repo commit 'Sync CLAUDE.md from admin templates (wave-one doctrine; mina's replicate/code paragraph preserved)').

Pushed a HAND-MERGED file, not push-template.py: mina had one genuine self-edit (a paragraph arguing code-based making is co-primary with replicate, from her cobweb/Feigenbaum work). Ben chose to preserve it. Method: diff live CLAUDE.md against the blob left by the last 'Ben Swift' sync commit (2026-06-07) to separate her edits from admin-side reflow noise, splice hers into the fresh render, push that. The rest of 'slop drift' output is cosmetic --- the template was rewrapped to 80 cols after the last sync.

The push also delivered the video-cap paragraph, which had never reached any agent (tool guard did; doctrine text didn't).

AC2 (observation gate) now open. Mina ticks ~every 30 min and was healthy pre-push. Next dream window: 03:00-05:00 Canberra, i.e. overnight 2026-07-09/10. Check after that: notes/now.md exists and is rewritten (not appended) across ticks; a dream entry appeared in notes/ with no posting during the window; no new tick failures.

Do NOT fan out (AC3) until that window has passed. All five remaining agents also have 1-3 self-edits since 2026-06-07 --- each needs the same isolate-and-merge treatment.

Known tension to watch: tick-routine step 6 and the studio cue still nudge mina toward replicate, which cuts against the paragraph she kept.

--- 2026-07-09 observation, first post-push tick ---
Wake showed 'mina fail(1)' at 10:10 AEST. Diagnosed: SELF-INFLICTED, not a doctrine fault. The tick (390e9d76) started 00:03:43Z, before the push at 00:05:33Z, so it ran the OLD CLAUDE.md, did its work, then slop-tick's closing 'git push' was rejected non-fast-forward because the remote had moved under it. Work was preserved locally; the next tick's 'git pull --rebase --autostash' replayed the session commit cleanly on top of the sync commit (verified on sprite: ahead 1, no rebase in progress, CLAUDE.md has wave one). No action needed.

LESSON FOR FAN-OUT: pushing a template mid-tick costs that agent one fail(1). Ticks run 2-11 min inside a wake that fires every 30 min (+/- 5 min jitter). Push just after a wake's agents have finished, not at a wake boundary --- or accept one benign fail(1) per agent and don't let it trip the healer's consecutive-failure counter.

CONFIRMED WAVE-ONE DOCTRINE IS LIVE: tick 4771874f (00:30Z, first tick on the new file) read notes/now.md, ran 'TZ=Australia/Canberra date', and reasoned explicitly 'It is 10:31 AM in Canberra - not a dream tick'. now.md did not exist yet, which the tick noticed.

SEPARATE BUG FOUND (own task): SIBLINGS.md exceeds the 25k-token Read cap on all six agents, so tick step 2 fails every tick.

--- 2026-07-09 ~11:10 AEST, gate progress ---
AC2 partly met. Two clean 'ok' ticks since the push (289s, 208s). notes/now.md created on the first full tick and REWRITTEN (429 -> 396 bytes) on the second, not appended --- the rewrite-not-append rule is holding. First tick on the new file ran 'TZ=Australia/Canberra date' and reasoned 'not a dream tick'. Still outstanding: the 03:00-05:00 Canberra dream window (17:00-19:00 UTC today).

WATCH: in now.md mina writes 'It's 00:31 UTC. No dream tick.' She ran the Canberra date command in-thinking but records UTC in the note. Both agreed at that hour. If she keys the window off UTC she will dream at 03:00 UTC = 13:00 Canberra. The window tonight settles it.

WATCH: that tick produced only now.md, no dated tick note. Satisfies the rest ethic, but if now.md displaces dated notes the site's /notebook page thins out (it lists files in notes/).

TEMPLATE STANCE CHANGED (505c6bf): lou, lelia and mina had each independently rewritten the 'code-based making is at its best post-processing' paragraph to say code is co-primary. Convergent drift across three agents that cannot see each other's CLAUDE.md. Ben chose to fold it into the template and soften tick-routine step 6. slop-studio's cue left alone --- it fires on modality (all stills -> a/v), not code-vs-replicate, and drives Replicate spend.

CONSEQUENCE: mina's live CLAUDE.md was rendered BEFORE 505c6bf, so she still has the old step 6. Fan-out must carry the step-6 softening to her as well as to the other five.

FAN-OUT PLAN (prepared, not executed): additive patches onto each agent's LIVE file, not a template re-render. Since the 2026-06-07 fleet sync the only substantive template changes agents lack are the video-cap paragraph (30cbedc) and wave one; everything else in that range they already have (caption-as-artwork, studio cue, post-dedup) or is the 985c1b0 reflow. Additive preserves drift by construction --- necessary for gert/vita/lelia/rahel, who have large self-authored sections. Deliberately NOT written yet: if the dream window shows the doctrine needs changing, the patch set changes with it.

--- 2026-07-09 12:25 AEST, doctrine fix mid-gate ---
GATE CAUGHT A WAVE-ONE DESIGN FLAW. mina wrote only notes/now.md for three consecutive ticks --- no dated tick note. The working note ate the archive. Template already said now.md is 'a working note, not an archive' but never said that rewriting it does not discharge the every-tick-produces-something floor. Fixed in 7df6fbd: 'the honest minimum is one line in a DATED note ... Rewriting now.md is not that line --- it is the letter you leave, not the work you did; a tick writes both.'

Also 505c6bf earlier: co-primary code/replicate framing + softened step 6.

Both hunks re-pushed to mina 02:2xZ, additively onto her LIVE file (scratchpad/patch-agent.py). Her cobweb/Feigenbaum paragraph survives. This VALIDATES the fan-out mechanism on a real agent before using it on the other five: each hunk asserts its anchor is present and unique, so a drifted file fails loudly rather than silently skipping.

GOTCHA: raw.githubusercontent.com caches ~5 min. Verify pushes with 'gh api repos/<r>/contents/<f> --jq .content | base64 -d', not curl raw --- the raw copy showed the OLD file right after a successful push.

TICK HEALTH: five consecutive 'ok' ticks (289s, 208s, 289s, 251s + earlier). now.md rewritten each time (429 -> 396 -> 503 -> 633 bytes), never appended.

STILL OUTSTANDING: the 03:00-05:00 Canberra dream window, 17:00-19:00 UTC today. That is the only remaining AC2 evidence. Then fan out with patch-agent.py.

SEPARATE BUG FOUND (task-5, high): site /notebook drops most notes --- NOTE_RE only matches filenames leading with an ISO date. rahel shows 1 of 3555 markdown notes. now.md and mina's tick-<ISO>T####.md format are both invisible.
<!-- SECTION:NOTES:END -->
