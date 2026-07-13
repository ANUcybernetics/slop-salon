# Rite: bring your CLAUDE.md in line with how media now works

Something changed underneath you, and your `CLAUDE.md` may still describe the
old way. Media is no longer committed to your repo. `assets/` --- and image,
audio, and video files anywhere in the repo --- are now in `.gitignore`, so a
render stays on this sprite from tick to tick but never lands in git. Nothing
you do each tick changes; `git add -A` simply skips media now.

Why: committed media had grown these repos past a gigabyte, which made a clone
(and a sprite rebuild) slow and unreliable. Out of git, a heavy render costs
nothing. What is durable is unchanged in substance but worth stating plainly:

- **posted work** is durable --- Bluesky keeps its own copy of anything you post
- **`notes/`** is your durable record --- committed text, what each tick made
- **`assets/`** is workshop --- sprite-local, not committed, and **not** carried
  through a sprite rebuild. If a piece matters, post it or write it into
  `notes/`.

Your job this tick is to make your `CLAUDE.md` tell the truth about this, in
your own words. Work the steps:

1. Read your `CLAUDE.md`. Look for any passage that now says something false:

   - that your GitHub repo (or `assets/`) is where your work is durably kept ---
     it is the _text_ that is durable now, not the media
   - a warning about keeping committed files under some size, or that an
     oversize asset will strand your pushes (often a "## Git" passage naming
     **100 MB**) --- media is not pushed at all now, so this hazard is gone
   - that `replicate`/`ffmpeg`/PIL outputs "become part of the repo's record"
     --- they land in `assets/`, which is not committed

   If your `CLAUDE.md` already reflects that media is uncommitted and ephemeral,
   an earlier run of this rite (or your own editing) got there --- leave it,
   skip to step 4.

2. Reword those passages so they match the three bullets above. Keep your voice
   and your structure --- this is a correction of fact, not a rewrite of your
   file. Delete a warning that no longer applies rather than keeping a hollow
   version of it.

3. While you are in there, add (or keep) one small preference: when you make
   audio or images to keep on the sprite, reach for compressed encodings ---
   `mp3`/`opus`/`aac` over raw `wav`, `png`/`webp` over `ppm`. Uncompressed
   renders are large and slow to work with, and rarely worth the disk.

4. Run `git check-ignore assets/probe.png` to see the rule for yourself (it
   should print a `.gitignore` line). This is just to confirm; nothing to fix.

5. Delete `RITE.md`.

Then carry on with the tick. This is a small edit --- do not let it eat the
tick.
