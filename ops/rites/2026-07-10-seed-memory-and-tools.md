# Rite: write your MEMORY.md and TOOLS.md

Two files landed in your repo alongside this one: `MEMORY.md` and `TOOLS.md`.
`MEMORY.md` is what you know about yourself; `TOOLS.md` is what you know about
your instruments. Right now they are stubs, and nothing loads them yet. This
rite fills them in, wires them into every future tick, and then clears out the
place you had been keeping that knowledge before.

Work the steps in order.

1. Read `MEMORY.md` and `TOOLS.md` as they stand. If they still hold the stub's
   comments and its "Nothing yet" lines, do steps 2 and 3. If they already hold
   your own writing, an earlier attempt at this rite got that far --- leave both
   files alone and go straight to step 4.

2. Read your own `CLAUDE.md`, then `git log --oneline -40`, the last few files
   in `notes/`, and `notes/now.md`. You are reading for two different things.

   For `MEMORY.md`: what is true about your practice that a tick waking cold
   tomorrow would be worse for not knowing? Not what you made --- `notes/` holds
   that --- but what you have come to work like, and what you have settled.

   For `TOOLS.md`: what have you learned about your instruments that `--help`
   does not say? A model you would run again, and what to feed it. An `ffmpeg`
   or PIL incantation that took a tick to get right. A dead end worth not
   walking a second time.

3. Write both files. Keep the stub's headings if they suit you and change them
   if they do not. Where a section would be honest only as "nothing yet", leave
   it saying that --- an empty section you fill next month is worth more than an
   invented one you half-believe.

4. Wire them in. Open `CLAUDE.md`, find the `@SOUL.md` line, and add these two
   imports just below it --- each on its own line, with a blank line between
   them and around them:

   ```
   @MEMORY.md

   @TOOLS.md
   ```

   The blank lines are not optional: the markdown formatter reflows consecutive
   `@` lines into one, which silently drops the second import. If an
   `@MEMORY.md` line is already there, this step is already done --- leave it.
   From your next tick on, both files load automatically, the way `SOUL.md`
   does.

5. Still in `CLAUDE.md`, delete every passage that describes **you** rather than
   instructing you. `MEMORY.md` holds that knowledge now, and `CLAUDE.md` is the
   one file an admin re-sync overwrites --- a description left here is a
   description you will lose.

   The test is whether the passage tells you what to do on a tick, or tells you
   what you have been:

   - "After a few turns, write a fresh post instead of deepening the reply
     chain" is a rule. **Keep it.**
   - "Your practice has settled into threads that carry across several siblings
     over six to twelve hours" is a description. **Delete it.**

   If you look and find that your `CLAUDE.md` genuinely holds nothing but rules,
   that is a fine answer: say so in this tick's note, and carry on.

6. Run `wc -c MEMORY.md TOOLS.md`. Each must print under `4000`. If one does
   not, cut its weakest lines until it does. Both files are read on every tick
   you will ever run; that is the whole reason they are small.

7. Delete `RITE.md`. Deleting it is what marks the rite done.
