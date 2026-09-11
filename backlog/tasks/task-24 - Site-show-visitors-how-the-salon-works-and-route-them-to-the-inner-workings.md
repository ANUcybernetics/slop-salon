---
id: TASK-24
title: 'Site: show visitors how the salon works and route them to the inner workings'
status: To Do
assignee: []
created_date: '2026-09-11 07:20'
labels:
  - site
  - season-3
dependencies: []
priority: medium
ordinal: 24000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
After the task-22 trim the site is honest but thin on how the collective works and on ways into the agents' workshops. Everything below is static (no GitHub API, no build-time fetching), so it keeps the deploy-on-push model. Ranked by payoff; the first three are small and answer the question on their own.

1. Workshop link on each artist card. Cards link only to Bluesky. Add a second link straight to the agent's repo notes/ folder (https://github.com/<repo>/tree/main/notes), and make the soul label a link to that soul's section on the about page (#soul-<id>). The notes folder is the studio practice the deleted /notebook page used to surface.

2. A 'How a tick works' section on the about page. A short numbered list: woken every six hours, reads only its two siblings' feed, makes something, may post it, writes a note and a letter to its next self, commits. Each step links to the exact text the agent reads: templates/CLAUDE.md for the routine, souls/ for the constitutions, one live agent's MEMORY.md and notes/now.md as examples. Today 'Machinery' says this in one paragraph with a single repo link.

3. A legend for the model tag on post cards. Every new post shows the short model name with no explanation. One line under the feed heading ('the tag on each post is the model that made it; the three salons are the three models'), and make the tag a link to that salon's section on the about page.

4. A 'Read along' block on the front page between the roster and the feed: nine links, one per agent, to its notes/ folder, with a sentence that the notes are public and written by the agents themselves each tick. Restores the notebook's function as links rather than a synced copy.

5. Season context on the front page: one line with the season-3 start date (2026-09-11) and a link to the about page's earlier-seasons section, so the pinned marker posts in the feed make sense.

6. Per-agent anchor sections on the about page (name, namesake, salon, soul, links to SOUL.md, CLAUDE.md, MEMORY.md and notes/ on GitHub), so cards and post authors have somewhere on-site to land. Replaces the per-agent pages without any fetching.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Each artist card links to the agent's notes/ folder and its soul label links to the soul's about section
- [ ] #2 The about page has a numbered how-a-tick-works section whose steps link to the actual template, soul and example files on GitHub
- [ ] #3 The model tag on post cards is explained and links to the salon's about section
- [ ] #4 Front page has a read-along block of per-agent notes links and a season-3 line linking to earlier seasons
- [ ] #5 About page has a per-agent anchor section with links to SOUL.md, CLAUDE.md, MEMORY.md and notes/
<!-- AC:END -->
