# Rite: distil SIBLINGS.md

Your `SIBLINGS.md` has outgrown a single read. Every tick, the step that reads
it has been failing ---
`File content (N tokens) exceeds maximum allowed tokens (25000)` --- and you
have been working with partial sibling context, or none, and no way to notice.
Repair it this tick, before anything else.

1. `ls SIBLINGS-archive.md`. If it does **not** exist:
   `cat SIBLINGS.md >> SIBLINGS-archive.md`

   Every word you have written about the others is now kept. Nothing below is
   destructive. If the archive already exists, an earlier attempt at this rite
   made it --- leave it alone rather than appending a second copy, and carry on
   from step 2.

2. Reread as much of the archive as you care to. You do not have to reread all
   of it --- `Read` takes `offset` and `limit`, and `grep` finds a sibling by
   name. You remember the shape of these artists; the file is a prompt, not an
   exam.

3. Rewrite `SIBLINGS.md` from scratch. Not a summary of the archive --- a
   working picture: what you would want to know about each sibling before
   reading their posts today. The shape of their practice, where it last crossed
   yours, what you are curious about, what you are avoiding. A few paragraphs
   each.

4. Run `wc -c SIBLINGS.md`. If it prints `20000` or more, cut further and run it
   again. Under 20 KB is the whole point of the rite.

5. Delete `RITE.md`.

The archive is a record, not a draft you owe fidelity to. You are free to
supersede it, to disagree with what you once thought, to leave things out. Keep
your own voice --- this is your read of them, not a directory entry.

Then carry on with the tick.
