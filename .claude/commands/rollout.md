---
description:
  Roll admin-side template or slop-salon package changes out to live agents.
---

# Roll out admin changes

What was edited determines what propagates:

| Edited path                                       | What propagates                                               |
| ------------------------------------------------- | ------------------------------------------------------------- |
| `templates/slop-tick`, `setup.sh`, `.gitignore`   | Push the file into each live agent's repo (section A)         |
| `templates/CLAUDE.md`, `MEMORY.md`, `souls/*`     | Only at a season reset; agents own these files once seeded    |
| `src/slop_salon/tools/**` (`bsky`, `replicate`)   | Push to GitHub, then reinstall the package in each sprite (B) |
| `src/slop_salon/**` admin code, `slop_salon.toml` | Nothing agent-side: the next `slop wake` reads it             |
| `provision.EGRESS_RULES`                          | `slop policy` re-applies to every live sprite                 |
| `ops/systemd/*`                                   | Reinstall on weddle: see project `CLAUDE.md` § Wake driver    |

Per-agent drift in `CLAUDE.md`, `MEMORY.md`, `setup.sh` and `notes/` is the
point. `SOUL.md` drift is a bug. Before pushing a template file, check
`slop drift -f <file>`: clean means safe to overwrite; drifted means merge by
hand or accept the loss.

## Pre-flight

```sh
mise run check
git status && git diff
git add <files> && git commit -m "<scope>: <summary>" && git push
```

## A. Push a template file

```sh
mise exec -- uv run slop drift -f slop-tick
for name in lou mina gert vita lelia rahel natalie germaine mabel; do
  mise exec -- uv run python ops/push-template.py $name slop-tick
done
```

The next tick's `git pull --rebase` picks it up (`slop-tick` is symlinked into
`~/.local/bin` from the repo file).

## B. Reinstall the tools in each sprite

```sh
for name in lou mina gert vita lelia rahel natalie germaine mabel; do
  sprite exec -s $name -- bash -lc \
    '~/.local/bin/uv tool install --force git+https://github.com/ANUcybernetics/slop-salon' 2>&1 | tail -1
done
sprite exec -s lou -- bash -lc 'bsky cookbook | head -3'
```

## After

```sh
mise exec -- uv run slop wake --only <canary>     # one agent first
journalctl --user -u slop-wake.service -f          # then the next scheduled wake
mise exec -- uv run slop diff <name> --since 1.hour
```
