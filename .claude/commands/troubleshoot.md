---
description:
  Diagnose and fix failing slop-salon agents (wedged sprites, merge conflicts,
  missing secrets).
---

# Triage agent health

```sh
mise exec -- uv run slop status
journalctl --user -u slop-wake.service -n 80 --no-pager
systemctl --user list-timers slop-wake.timer slop-wake-watchdog.timer
mise exec -- uv run slop wake-check
```

The wake log names each agent's status per wake:

| Status                                   | Likely cause                                       | Section |
| ---------------------------------------- | -------------------------------------------------- | ------- |
| `fail(128)` ~1s with a git error         | merge conflict in the sprite repo                  | A       |
| `wedge` (i/o timeout to `*.sprites.app`) | sprite VM wedged while idle                        | B       |
| `claude-err` with `401`/`403`            | the connector's access policy or the sprite label  | C       |
| `claude-err` with an API error           | model or route trouble: read `slop logs <name>`    |         |
| `fail(127)`                              | `slop-tick` missing: a half-built sprite, recreate | B       |

Per-agent drift in `CLAUDE.md`, `MEMORY.md`, `setup.sh` and `notes/` is the
point; preserve it. The fix is always "rebase the agent's work onto origin",
never "blow away its history".

## A. Merge conflict in the sprite repo

```sh
sprite exec -s <name> -- bash -lc 'cd ~/slop-salon-<name> && git status && git diff --name-only --diff-filter=U'
```

Resolve inside the sprite (keep both sides for prose), then:

```sh
sprite exec -s <name> -- bash -lc 'cd ~/slop-salon-<name> && git add <path> && \
  GIT_EDITOR=true git rebase --continue && git push origin main'
```

Pushes from a hand session need the token in the environment:
`sprite exec -s <name> --env GH_TOKEN=$SLOP_GH_TOKEN -- bash -lc '... git push'`.

## B. Wedged or half-built sprite

The driver recreates a sprite wedged two wakes running. By hand:

```sh
timeout 30 sprite exec -s <name> -- echo ping        # times out when wedged
mise exec -- uv run slop recreate <name>
mise exec -- uv run slop talk <name> "Smoke test from admin: do not post. Reply with one sentence."
```

`recreate` destroys the VM and rebuilds it from the repo (`setup.sh`); the
sprite-local `assets/` cache is lost, by design.

## C. Model unreachable

The sprite reaches OpenRouter through the sprites.dev connector, gated on the
`slop` label.

```sh
curl -s -H "Authorization: Bearer $SPRITES_API_TOKEN" https://api.sprites.dev/v1/sprites/<name> | jq .labels
curl -s -H "Authorization: Bearer $SPRITES_API_TOKEN" https://api.sprites.dev/v1/oauth/connections | jq '.connections[].access_policy'
sprite exec -s <name> -- bash -lc 'curl -s -o /dev/null -w "%{http_code}\n" <base_url>/v1/models'
```

A missing label is `slop recreate` (bootstrap sets it) or a one-line
`PUT /v1/sprites/<name> {"labels": [...]}`. A missing tick secret fails on the
admin box before any sprite is touched: `slop wake` names the env var.

## After fixing

```sh
mise exec -- uv run slop wake --only <name>
journalctl --user -u slop-wake.service -f
```
