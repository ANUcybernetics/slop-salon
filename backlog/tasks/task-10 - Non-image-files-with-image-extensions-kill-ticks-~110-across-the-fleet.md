---
id: TASK-10
title: Non-image files with image extensions kill ticks (~110 across the fleet)
status: Done
assignee: []
created_date: '2026-07-10 02:01'
updated_date: '2026-07-10 03:21'
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
- [x] #1 Mechanism confirmed (which writer produces the JSON-as-image and directory-as-image files)
- [x] #2 replicate tool refuses to write a non-image body, and refuses an --output that names a file
- [x] #3 Existing landmines swept from all six repos, content preserved where it is real
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
AC1 CONFIRMED 2026-07-10. There are TWO writers, not one.

1. THE JSON-AS-IMAGE FILES: the tool's downloader is dead code.

   replicate.run() returns replicate.helpers.FileOutput objects, which are NOT
   str subclasses (MRO: FileOutput -> SyncByteStream -> AsyncByteStream ->
   object). replicate_run.run() gates its download on
   _is_url(item), whose first line is `isinstance(value, str)` --- so the
   download branch never executes. Control falls to the else, which prints
   str(item), and FileOutput.__str__ yields the bare URL.

   So `replicate run ...` has never downloaded anything since the SDK began
   returning FileOutput. The agents improvised: mina's transcript shows
   `curl -s -L` --- no `-f` --- so an expired or missing replicate.delivery URL
   writes its 404 body, `{"detail": "requested file not found"}`, into the
   target file with exit status 0. That is every JSON-as-image file, and it also
   explains why the bad filenames are semantic (ghost-routes-1.webp) rather than
   replicate-shaped (out-0.webp): the agent chose the name on the curl -o.

   The directory-as-image files are the same improvisation (a curl -o into a
   path that was mkdir'd, or --create-dirs).

2. THE PYTHON-SCRIPT-AS-PNG FILES: agent error, lou specifically.

   assets/ghost-between.png and assets/frobenius-dispersion.png are both
   matplotlib scripts (`#!/usr/bin/env python3`). lou writes the script to the
   .png path she means it to *produce*. She has killed two ticks this way in one
   morning (01:38Z, 02:37Z). Renaming ghost-between.png to .py was the right
   repair; frobenius-dispersion.png still needs it.

THE FIX therefore has to restore the tool's download path, not merely harden it:
teach it FileOutput (use .read(), or httpx with follow_redirects on .url),
verify the body is not an error before writing, and refuse an --output that
names a file rather than a directory. Once `replicate run` actually downloads,
agents have no reason to curl.

AC2/AC3 DONE 2026-07-10.

Tool fixed (d374601, 91578b4) and reinstalled in all six sprites; smoke-tested
in-sprite. The old download test passed a str URL and mocked httpx wholesale, so
it never exercised the real path --- the new tests fail against the old code
(verified by stashing the fix).

Sweep applied under the tick flock, committed and pushed per agent:

  agent  delete  rename  flatten  rmdir
  lou    11      2       -        3
  mina   11      -       1        2
  gert   28      2       -        3
  vita   31      4       -        -
  lelia  22      -       -        2
  rahel  11      -       1        1

114 deletions, every one an error body (JSON `{"detail"...}`, S3 `<Error>
<Code>NoSuchKey`) or a zero-byte file --- nothing agent-authored was deleted.
The dry run surfaced two shapes the first pass would have got wrong: 127-byte
S3 XML errors (added to the delete rule) and short "placeholder" texts the
agents wrote themselves, which are renamed to .txt rather than removed. lou's
two matplotlib scripts became .py with their bytes intact.

Remaining landmines: 0 on every agent.
<!-- SECTION:NOTES:END -->
