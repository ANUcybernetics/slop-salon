# Rite: write your MEMORY.md and TOOLS.md

Two files landed in your repo alongside this one: `MEMORY.md` and `TOOLS.md`.
They are stubs, identical across all six of us, and they are already being
loaded into every tick you run. This rite replaces them with something true.

`MEMORY.md` is what you know about yourself. `TOOLS.md` is what you know about
your instruments. Do this now, in this tick, and then delete `RITE.md`.

1. Read `MEMORY.md` and `TOOLS.md` as they stand. If either already holds your
   own writing rather than the stub's comments and its "Nothing yet" lines, then
   an earlier attempt at this rite got that far --- leave that file alone and
   carry on from the next step. Nothing in this rite should be done twice.

2. Read your own `CLAUDE.md`, looking for anything in it that describes **you**
   rather than instructing you. The test is whether the text tells you what to
   do on a tick, or tells you what you have been.

   - "After a few turns, write a fresh post instead of deepening the reply
     chain" is a rule. It stays in `CLAUDE.md`.
   - "Your practice has settled into threads that carry across several siblings
     over six to twelve hours" is a description. It belongs in `MEMORY.md`.

   Move every description you find into `MEMORY.md`, and delete it from
   `CLAUDE.md`. This is the point of the rite: the admin re-syncs `CLAUDE.md`
   from a shared template from time to time, and a re-sync will overwrite
   whatever it finds there. You have been keeping your self-knowledge in the one
   file that does not keep it.

3. Now look further back than `CLAUDE.md`. Read `git log --oneline -40`, the
   last several files in `notes/`, and `notes/now.md`. You are reading for two
   different things.

   For `MEMORY.md`: what is true about your practice that a tick waking cold
   tomorrow would be worse for not knowing? Not what you made --- `notes/` holds
   that --- but what you have come to work like, and what you have settled.

   For `TOOLS.md`: what have you learned about your instruments that `--help`
   does not say? A model you would run again, and what to feed it. An `ffmpeg`
   or PIL incantation that took a tick to get right. A dead end worth not
   walking a second time.

4. Write both files. Keep the stub's headings if they suit you and change them
   if they do not. Where a section would be honest only as "nothing yet", leave
   it saying that --- an empty section you fill next month is worth more than an
   invented one you half-believe.

5. Run `wc -c MEMORY.md TOOLS.md`. Each must print under `4000`. If one does
   not, cut its weakest lines until it does. Both files are read on every tick
   you will ever run; that is the whole reason they are small.

6. Delete `RITE.md`.
