---
id: TASK-3
title: >-
  Roll out behaviour-doctrine waves (rest ethic, now.md, rites, dream ticks;
  then MEMORY.md + TOOLS.md)
status: In Progress
assignee: []
created_date: '2026-07-08 22:51'
updated_date: '2026-07-09 19:29'
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
- [x] #2 Mina observed over multiple natural ticks, including at least one 03:00-05:00 Canberra window: now.md is being maintained, dream-tick behaviour is sane, no new tick failures
- [x] #3 Wave one fanned out to the other five live agents, each with drift reviewed before push
- [ ] #4 Wave two drafted and rolled out (same canary gate): capped ~40-line MEMORY.md with @MEMORY.md import, TOOLS.md template stub, existing agents seeded via the first RITE.md push
- [x] #5 Admin CLAUDE.md tunables/architecture notes and project memory updated to reflect what is live
<!-- AC:END -->



## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
--------------------------------------------------
--------------------------------------------------
--------------------------------------------------
--------------------------------------------------
--------------------------------------------------
--------------------------------------------------
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

--- 2026-07-09 13:10 AEST, DREAM TICK BUG CONFIRMED AND FIXED (e23d40d) ---
The canary dreamed at 13:02 Canberra, in the afternoon. Transcript: she ran 'TZ=Australia/Canberra date', read 'Thu Jul 9 13:02:12 AEST 2026', then reasoned '13:02 AEST = 03:02 UTC. That's within the dream tick window' and committed --- 'Dream tick (13:02 AEST = ~03:02 AEDT)'. She converted the studio hour to UTC and tested THAT against 03:00-05:00. Net effect: dream ticks fire 13:00-15:00 Canberra and NEVER during the real 03:00-05:00 window.

SECOND DEFECT, unpredicted: she called getTimeline at 03:02:47 and only concluded 'dream tick' at 03:03:41. The doctrine says a dream tick must not read the timeline, but the routine put the timeline at step 4 and the dream check nowhere. Compliance was impossible as written.

Both fixed in e23d40d:
- tick routine step 1 is now 'TZ=Australia/Canberra date +%H' --- ONE number --- 'if it prints 03 or 04, this is a dream tick: skip steps 4 and 5'. Renumbered 1-8.
- Dream ticks section says outright: do not convert that hour to UTC, do not test a UTC clock against this window, 03:00 UTC is the middle of a Canberra afternoon.

Pushed to mina 03:1xZ additively (patch-agent.py now carries 4 hunks; the two earlier ones report SKIPPED on her since already applied --- the anchor assert makes that visible rather than silent).

DREAM PROTOCOL ITSELF IS SOUND: on the (mistimed) dream tick she did not post, reread old notes, made assets/cocycle-chambers.png, wrote notes/dream-2026-07-09.md, distilled into now.md. Only the trigger was wrong.

FIX IS FALSIFIABLE TWICE TODAY:
- negative test: ticks at 03:31/04:01/04:31 UTC are 13:31-14:31 Canberra, inside the OLD false band. She must NOT dream.
- positive test: 17:00-19:00 UTC is 03:00-05:00 Canberra. She MUST dream, and must not read the timeline first.
Fan-out only after both pass.

STILL OPEN: the dated-note fix (7df6fbd) did not change behaviour on its first tick --- she wrote only now.md again. Watch. NB the dream tick DID produce a dated note (dream-2026-07-09.md).

NB for fan-out: hunks 3 and 4 will NOT match vita (rewrote steps 5-6) or lelia (added an exception para) --- patch-agent.py will report SKIPPED loudly. Merge those two by hand.

--- 2026-07-09 13:45 AEST, step-9 fix + fan-out method corrected ---
NEGATIVE DREAM TEST PASSED. 03:31Z tick (13:31 Canberra, inside the OLD false band): she ran 'TZ=Australia/Canberra date +%H', got 13, reasoned 'Hour is 13 --- not a dream tick (dream ticks are 03 or 04). Continue with step 2.' No conversion. Timeline read only after the check. Step-1 restructuring worked on its first tick.

DATED-NOTE FIX NEEDED A SECOND ATTEMPT. The prose version (7df6fbd) was ignored for two consecutive ticks. Reworked as an explicit numbered step 9 (e4d767a) and pushed. LESSON, generalisable: agents execute the numbered tick routine and skim the surrounding prose. The dream fix landed instantly because it became step 1; the dated-note fix failed because it was a sentence in a paragraph. Put requirements in the checklist.

FAN-OUT METHOD CORRECTED --- the additive patch plan was WRONG for the other five. Dry run (patch-agent.py against all five live files) reported 5/5 hunks 'NEEDS MERGE' for every agent. Two causes:
  1. their CLAUDE.md files are UNWRAPPED (max line 824-826 chars); only the admin template was reflowed to 80 cols by 985c1b0. Wrapped anchors can never match.
  2. they have NONE of wave one (no now.md / RITE.md / dream section / video-cap). The five hunks are deltas ON TOP of wave one --- the wrong patch set entirely.
So fan-out is RECONSTRUCTIVE, as mina's first push was: render the current template (wave one + all four corrections) and re-insert each agent's self-authored passages. Their drift is enumerable: lou 1 rewritten para; gert 2 added blocks; vita step-level edits + 1 added para; lelia 3 passages; rahel a shortened studio-state para + a whole '## What rahel actually does' section.

Also: patch-agent.py now distinguishes 'already there' from 'NEEDS MERGE' (compares the NEW text, not just the anchor) --- the old message conflated them. Its mina 'step 6 NEEDS MERGE' was a false alarm: the dream hunk renumbered 6 to 7.

REMAINING GATE: positive dream test, 17:00-19:00 UTC today (03:00-05:00 Canberra). She must dream, and must not read the timeline first. Fan out only after that passes.

--- 2026-07-09 14:20 AEST, step 9 works ---
The 04:15Z tick wrote BOTH notes/tick-2026-07-09T1400.md and notes/now.md. Step 9 landed on its first tick, confirming the lesson: put requirements in the numbered routine, not the prose. (Tick took 717s vs the usual 200-290s; watch whether the extra step costs time consistently.)

AC2 evidence now complete except the positive dream test:
  - now.md maintained and REWRITTEN, never appended (429/396/503/633/535/654 bytes across ticks)
  - dated notes resume after step 9
  - dream trigger: negative test passed (hour 13 -> stayed awake, timeline read only after the check)
  - no new tick failures; the single fail(1) was my mid-tick push, self-healed
Outstanding: positive dream test at 17:00-19:00 UTC (03:00-05:00 Canberra).

FAN-OUT IS BUILT AND VERIFIED, NOT PUSHED. scratchpad/fanout.py reconstructs each of the five from the current template + that agent's own drift, asserting per-agent phrases survive and that steps number 1-9 with the dream check before getTimeline. lou/gert/rahel are clean insertions. vita and lelia drifted INSIDE the tick routine that wave one restructures, so their steps 7 (and vita's 3, 8) are hand-blended, not verbatim --- Ben should skim those two before or after push.

Filename note: mina names dated notes by Canberra hour (tick-2026-07-09T1400.md). That collides with the future-dated notes she fabricated on 2026-07-08 (task-6) --- her real note landed as a MODIFY of one. Harmless; she overwrites filler. Those names are invisible to /notebook regardless (task-5).

--- 2026-07-09 23:40 AEST, claude-err on the canary (NOT wave one) ---
Wake reported 'mina claude-err 585.8s'. Cause: she Read() 13 image assets while deciding what to post; Claude Code loads images into the prompt visually and vLLM refuses more than 8 --- 'API Error: 500 ... At most 8 image(s) may be provided in one prompt.' The whole request fails and the tick dies after 10 min of real work. slop-tick still exits 0, so it surfaces as claude-err, not fail.

DOES NOT FAIL AC2. She threw the same claude-err at 07:50 and 08:31 the same day, BEFORE the 10:05 wave-one push. Pre-existing, not a new tick failure. Logged as task-7 (high). Last-tick image-read counts: mina 13, rahel 2, others 0 --- mina's habit trips it, but the cap is server-side and any agent can.

Deliberately NOT fixed mid-gate: it is orthogonal to wave one and fixing it now would add a variable to the dream-window observation. Note the fix belongs in the NUMBERED tick routine, per the step-9 lesson.

Only one claude-err, so no heal alert (needs 2 consecutive). Watch for a second.

--- 2026-07-10 03:10 AEST, POSITIVE DREAM TEST PASSED --- AC2 COMPLETE ---
The 03:04 Canberra tick: 'Hour is 03 in Canberra - this is a dream tick. I should skip steps 4 and 5 (notifications and timeline) and go straight to reading notes/git log for dream material.' Transcript contains NO getTimeline, NO listNotifications, NO createRecord. Last Bluesky post was 16:06Z, an hour before the window opened; nothing during it. She wrote notes/tick-2026-07-10T0300-dream.md (which doubles as step 9's dated note, exactly as the doctrine says) and rewrote now.md.

Both directions now proven: awake at hour 13 (negative test), dreaming at hour 03 (positive test). Six consecutive ok ticks since the isolated claude-err; no heal alert.

FAN-OUT DEFERRED ~2h BY CHOICE. At 03:10 four of five agents were mid-tick, and more importantly the window is open: pushing now would make every agent's FIRST wave-one tick a dream tick (no timeline, no notifications, no posting until 05:00), i.e. their first exposure to the doctrine would be the atypical path, five at once, overnight, with untested dream behaviour. Push after 05:00 Canberra instead so each agent's first wave-one tick is ordinary and their first dream comes tomorrow night after a normal day.

Merged files rebuilt against template HEAD e4d767a and re-verified (steps 1-9, dream check before getTimeline, per-agent drift asserted).

--- 2026-07-10 05:20 AEST, FAN-OUT COMPLETE (AC3) ---
Pushed reconstructed CLAUDE.md to lou, gert, vita, rahel, lelia after the dream window closed and each sprite was verified idle (pgrep -x claude == 0; lelia waited one poll). Verified via API (not raw CDN): all five live files byte-identical to the built merges; all six agents now have every doctrine element, their own drift intact, and the dream check before getTimeline.

Four dream ticks observed on the canary in total, all compliant (0 getTimeline / 0 listNotifications / 0 createRecord), and she woke correctly at hour 05, making assets/transit.png. Window boundary respected in both directions.

MINOR, not fixed: two dream ticks land in the same hour (30-min cadence, hour-granularity filenames), so their dated notes collide. mina disambiguated once with a '-b' suffix and once wrote byte-identical content, so the second tick's entry vanished into a no-op commit. The note-per-tick record has a gap on dream nights. Not doctrine-breaking; revisit if it bothers.

NEXT: observe the fleet over the next wakes. Their first dream window is tonight 03:00-05:00 Canberra --- that is the first time five agents run dream ticks, and the first test of the doctrine on files that were NOT the canary's.
<!-- SECTION:NOTES:END -->
