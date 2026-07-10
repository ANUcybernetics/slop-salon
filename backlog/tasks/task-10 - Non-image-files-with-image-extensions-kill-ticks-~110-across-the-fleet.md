---
id: TASK-10
title: Non-image files with image extensions kill ticks (~110 across the fleet)
status: To Do
assignee: []
created_date: '2026-07-10 02:01'
updated_date: '2026-07-10 02:01'
labels:
  - bug
  - tools
dependencies: []
priority: high
ordinal: 10000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Reading a non-image file that has an image extension kills the tick. Claude Code dispatches Read on the extension, so the bytes go to vLLM as an image payload; PIL cannot parse them and the server returns 500, which claude surfaces as an API Error and exits 1. The tick still commits its partial work, so it shows up as claude-err.

FIRST SEEN 2026-07-10T01:38Z, lou: assets/ghost-between.png was a 5667-byte Python script (file: "Python script, Unicode text"). lou Read it while chasing a typo and the tick died. Repaired admin-side by renaming to .py (bytes and history preserved); no .py sibling had existed, so the script only survived under the .png name.

THEN A SWEEP FOUND IT IS EVERYWHERE. Counting files in assets/ whose extension is png/jpg/jpeg/webp/gif but whose mime type is not image/*:

  agent   json-as-image   directory-as-image   other   assets total
  lou     10              3                    3       1504
  mina    11              3                    0       1083
  gert    16              3                    13      1452
  vita    27              0                    7       1485
  lelia   22              2                    0        903
  rahel   11              2                    0       1647

~97 JSON files and 13 directories wearing image extensions. Each JSON one is a landmine: any tick that Reads it dies. Two observed shapes:

  eigenvalue-archive-0.webp  ->  {"detail": "requested file not found"}
  cancellation-0.webp/       ->  a DIRECTORY containing cancellation-0.webp (40450 B, a real image)

MECHANISM NOT YET CONFIRMED --- do not assume. Candidate causes, in the order worth checking:

(a) src/slop_salon/tools/replicate_run.py run() writes response.content after raise_for_status(). A 404 should raise, so a written 404 body means either the error body arrived with a 200, or httpx returned a 3xx (httpx does NOT follow redirects by default, and raise_for_status does not raise on 3xx) and the body got written.

(b) The --output option is a DIRECTORY (default assets/), and it is mkdir'd with parents=True. An agent passing --output assets/cancellation-0.webp would create a directory of that name and write the URL's basename inside. That fits the directory case exactly, except the inner filename is the agent's chosen name rather than a replicate basename --- so check what _filename_from_url actually returns for these URLs before believing it.

(c) The agents may be curling URLs themselves; curl without -f happily writes a 404 body to the output file. Several bad filenames are semantic (ghost-routes-1.webp) rather than replicate-shaped (out-0.webp), which points this way.

The fix probably has two halves: make the tool refuse to write a non-image body (sniff the magic bytes, or check content-type) and refuse a --output that names a file; and sweep the existing landmines out of the six repos.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Mechanism confirmed (which writer produces the JSON-as-image and directory-as-image files)
- [ ] #2 replicate tool refuses to write a non-image body, and refuses an --output that names a file
- [ ] #3 Existing landmines swept from all six repos, content preserved where it is real
<!-- AC:END -->
