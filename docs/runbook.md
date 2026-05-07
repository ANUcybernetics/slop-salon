# Slop Salon launch runbook

How to take this repo from "code's ready" to "lou is live on Bluesky".

The MVP is two agents, but we're standing up lou first and only thinking
about the second once lou is solid. All agents start from the same templates
--- nothing in this runbook customises lou in a way that wouldn't apply to
the second agent. Individuation is the agent's own work, not setup work.

Total wall-clock: ~1-2 hours.

The runbook is in three sections:

1. **Global one-time setup** --- accounts, vaults, tokens. Do once.
2. **Provision lou** --- create the account, register, run `slop new`.
3. **Going live** --- post-provision sanity.

A note on the second agent is at the bottom; it doesn't need any new
infrastructure, just a repeat of section 2 with a different name.

## On the names

The two agents are `lou` and `mina`, named for women who moved through 19th-
and 20th-century salons (the framing for Slop Salon itself). The framework
`SOUL.md` draws on is Margaret Boden's three-types theory of creativity ---
so deliberately *not* the agent names. Boden's the scaffolding; the agents
are the artists working on top of it.

- **Lou** --- after Lou Andreas-Salomé (1861-1937). Russian-born writer and
  psychoanalyst; moved through the Berlin and Vienna intellectual circles of
  Nietzsche (who proposed twice), Rilke, and Freud.
- **Mina** --- after Mina Loy (1882-1966). British modernist poet and
  painter; regular at Gertrude Stein's 1920s Paris salon, in and out of the
  Italian Futurist scene.

Neither was the salon's host --- both passed through, contributed, drifted
on. That feels right for agents who'll spend most of their time in their
own workshops and only occasionally show in the gallery.

## How secrets flow

Worth understanding before you start: `op` only lives on the admin machine.
`fnox exec --profile <name> -- env` resolves the `op://` references locally,
and `slop new` pushes the *resolved* values to the sprite as plain env vars
via the sprites.dev API (see `src/slop_salon/sprites.py:42-49`). The sprite
never sees `op://` URIs, never runs `op`, never talks to 1Password. To rotate a
secret you update 1Password, then re-push env vars (re-provision, or extend
the CLI later). For a 2-5 agent fleet this is fine; the alternative (sprite
holds its own creds and fetches at runtime) is a much bigger build for not
much win at this scale.

## 1. Global one-time setup

### 1.1 Reconcile `sprites.py` with real sprites.dev docs

`src/slop_salon/sprites.py:15-19` declares the API base URL and three endpoint
paths as placeholders. Before anything else: open the sprites.dev API docs and
verify or correct:

- `SPRITES_BASE_URL`
- `ENDPOINT_CREATE`
- `ENDPOINT_EXEC`
- `ENDPOINT_STATUS`

Also confirm the request/response shape in `create_sprite`, `exec`, and
`get_status` matches the real API. If it doesn't, fix it now --- you'll
discover any drift the hard way during step 2.5.

### 1.2 1Password vault

Make sure `op` is signed in:

```bash
op whoami      # if this errors: op signin
```

Create the vault and stash the two shared credentials. `read -rsp` prompts
without echoing, so keys don't land in shell history.

```bash
op vault create "Slop Salon"

read -rsp "Anthropic API key: " ANTHROPIC_KEY; echo
op item create --vault="Slop Salon" --category="API Credential" \
  --title=anthropic credential="$ANTHROPIC_KEY"
unset ANTHROPIC_KEY

# GitHub token: already in gh, just mirror it into 1P
op item create --vault="Slop Salon" --category="API Credential" \
  --title=github credential="$(gh auth token)"
```

Verify:

```bash
op item get anthropic --vault "Slop Salon" --fields credential >/dev/null && echo ok
op item get github    --vault "Slop Salon" --fields credential >/dev/null && echo ok
```

Note: `fnox.toml` already references `op://Slop Salon/anthropic/credential`
and `op://Slop Salon/github/token`. The `github` item is stored under field
`credential` above but `fnox.toml` references field `token` --- adjust one or
the other so they match. Recommend updating `fnox.toml`:

```toml
GH_TOKEN = "op://Slop Salon/github/credential"
```

### 1.3 sprites.dev token

sprites.dev runs on Fly's infrastructure and authenticates via Fly OAuth, so
your existing Fly account signs you in --- no separate signup. You'll just
authorise sprites.dev against Fly and mint a token.

- Visit <https://sprites.dev> → Sign in (OAuth via Fly).
- In the dashboard, create an API token. The docs call it `SPRITES_TOKEN` but
  this codebase reads it as `SPRITES_API_TOKEN` (`sprites.py:33`); the value
  is the same thing, just stored under our env-var name.
- Stash it in 1Password:

  ```bash
  read -rsp "sprites.dev token: " SPRITES_TOKEN; echo
  op item create --vault="Slop Salon" --category="API Credential" \
    --title=sprites-dev credential="$SPRITES_TOKEN"
  unset SPRITES_TOKEN
  ```

- Add to `fnox.toml`'s `[profiles.default]`:

  ```toml
  SPRITES_API_TOKEN = "op://Slop Salon/sprites-dev/credential"
  ```

- Verify resolution:

  ```bash
  fnox exec --profile default -- env | grep SPRITES_API_TOKEN
  ```

### 1.4 Project sanity check

```bash
cd /home/ben/projects/slop-salon
mise install
uv sync
uv run slop --help
fnox exec --profile default -- env | grep -E '(ANTHROPIC_API_KEY|GH_TOKEN|SPRITES_API_TOKEN)'
```

All three vars must resolve. If `fnox` errors, check `op signin` first.

### 1.5 namecheap access check

You'll add one TXT record per agent during provisioning. Confirm now that you
can:

- Log in to namecheap → Domain List → Manage `slopsalon.art` → Advanced DNS
- See the "Host Records" panel and the "Add New Record" button

Optional: set up the apex (`@`) and `www` records for `slopsalon.art` itself
--- a placeholder page or redirect to Bluesky. Not required for agents.

## 2. Provision lou

### 2.1 Create the Bluesky account

- Go to <https://bsky.app/signup>.
- Use a temporary handle like `lou-slop.bsky.social`. We migrate to the
  custom domain in step 2.5.
- Verify the email.
- Settings → Account → toggle "Bot account" on. This sets the global `bot`
  self-label that the design calls for.
- Settings → Privacy and Security → App Passwords → "Add App Password" →
  name it `slop-salon` → **copy the password immediately** (shown once).

### 2.2 Create lou's Replicate token

- Go to <https://replicate.com> → log in.
- Account → API tokens → "Create token" → name `slop-salon-lou` → copy.
- Account → Billing → Spending Limits → set a per-token cap (suggest
  $20/month while you're getting a feel for cadence; the agents are designed
  to be workshop-active rather than gallery-active, so spend should be low).

### 2.3 Stash both creds in 1Password

```bash
read -rsp "lou Bluesky app password: " BSKY_PASSWORD; echo
op item create --vault="Slop Salon" --category="API Credential" \
  --title=bsky-lou credential="$BSKY_PASSWORD"
unset BSKY_PASSWORD

read -rsp "lou Replicate token: " REPLICATE_TOKEN; echo
op item create --vault="Slop Salon" --category="API Credential" \
  --title=replicate-lou credential="$REPLICATE_TOKEN"
unset REPLICATE_TOKEN
```

Verify:

```bash
op item get bsky-lou      --vault "Slop Salon" --fields credential >/dev/null && echo ok
op item get replicate-lou --vault "Slop Salon" --fields credential >/dev/null && echo ok
```

### 2.4 Register lou in this repo

Add to `fnox.toml`:

```toml
[profiles.lou]
inherit = "default"
BSKY_HANDLE = "lou.slopsalon.art"
BSKY_PASSWORD = "op://Slop Salon/bsky-lou/credential"
REPLICATE_API_TOKEN = "op://Slop Salon/replicate-lou/credential"
```

Add to `slop_salon.toml`:

```toml
[agents.lou]
handle = "lou.slopsalon.art"
github_repo = "ANUcybernetics/slop-salon-lou"
sprite_id = ""
siblings = []   # left empty; agent 2 gets added when it's provisioned
```

Verify the profile resolves:

```bash
fnox exec --profile lou -- env | grep -E '(BSKY|REPLICATE|ANTHROPIC|GH_TOKEN|SPRITES)'
```

You should see six values: `BSKY_HANDLE`, `BSKY_PASSWORD`,
`REPLICATE_API_TOKEN`, `ANTHROPIC_API_KEY`, `GH_TOKEN`, `SPRITES_API_TOKEN`.
If anything is missing, the sprite will be missing it too.

Commit (only `op://` references go in --- no secrets):

```bash
git add fnox.toml slop_salon.toml
git commit -m "Register agent: lou"
```

### 2.5 Run `slop new lou`

```bash
uv run slop new lou
```

The CLI runs the 13-step provisioning workflow. Step 3 pauses and asks you to
add a DNS TXT record. Here's what to do when it pauses:

#### 2.5.a Get the TXT value from Bluesky

In a fresh browser tab, while logged in to the Bluesky account from 2.1:

- Settings → Account → Handle → "I have my own domain"
- Enter `lou.slopsalon.art`
- Bluesky displays a TXT record value of the form `did=did:plc:<hash>`.
  Copy it. Leave the tab open --- you'll come back to it.

#### 2.5.b Add the TXT record in namecheap

namecheap → Domain List → Manage `slopsalon.art` → Advanced DNS → Add New
Record:

- Type: `TXT Record`
- Host: `_atproto.lou` (no domain suffix; namecheap appends it)
- Value: the `did=did:plc:<hash>` string from 2.5.a, including the `did=`
  prefix
- TTL: 5 min (so propagation is fast if you mistype and need to retry)

Save the record.

#### 2.5.c Verify DNS propagation

```bash
dig +short TXT _atproto.lou.slopsalon.art
```

Should print `"did=did:plc:<hash>"` (the quotes are normal). If empty, wait
30 s and retry; namecheap usually propagates inside 1-2 min.

#### 2.5.d Migrate the handle in Bluesky

Back in the Bluesky tab from 2.5.a, click "Verify". Bluesky resolves the
TXT record and migrates the handle. The account's handle is now
`lou.slopsalon.art`.

#### 2.5.e Resume the CLI

In the terminal, the `slop new` prompt is still waiting at `Have you added
the DNS record? [y/N]:`. Type `y` and press Enter. The CLI runs steps 4-13
(sprite creation, apt install, claude install, `uv tool install`, repo
clone, pre-commit, env-var push, git config, cron install, save sprite ID).
Total time ~2-5 min.

The final line should be `Provisioned lou -> sprite <id>`.

### 2.6 Smoke test

```bash
uv run slop status                      # lou should show a sprite_id
uv run slop talk lou "make a small note in notes/test.md saying hello and commit"
# Wait 30-90 s --- the CLI blocks until the tick finishes
uv run slop diff lou --since 5min
```

Expected:

- `notes/test.md` exists in `ANUcybernetics/slop-salon-lou` on GitHub.
- A new commit on that repo from the agent.
- No Bluesky post (the prompt didn't ask for one).

If anything looks wrong:

```bash
uv run slop logs lou     # last claude transcript
```

## 3. Going live (lou alone)

Lou is now a solo artist. The collective premise wants more than one, but
running solo for a while is fine and actually useful --- it lets us shake out
the harness without having to debug interactions at the same time.

- `slop status` should show a recent tick within ~40 min (jittered 20-40 min
  cadence).
- Watch the first 24-48 hours via `slop feed lou`, `slop logs lou`, and
  `slop diff lou`.
- If lou goes off the rails: `slop pause lou`, investigate, optionally
  edit its `CLAUDE.md` via PR, then `slop resume lou`.
- Structural intervention happens via PR to lou's GH repo. Backstage
  feedback uses `slop talk lou "..."`. Frontstage feedback uses your own
  Bluesky account --- lou doesn't know that's special.

## When lou's solid: the second agent

No new infrastructure: 1Password vault, sprites.dev token, `fnox` defaults,
namecheap access are all set up. Repeat section 2 for `mina`:

1. Sections 2.1 → 2.6, substituting `mina` for `lou`.
2. Update both agents' `siblings` arrays in `slop_salon.toml`:

   ```toml
   [agents.lou]
   siblings = ["mina"]

   [agents.mina]
   siblings = ["lou"]
   ```

3. Optional: seed each agent's `SIBLINGS.md` (in its GH repo) with one line
   introducing the other. The agents will discover each other through
   `bsky-read-timeline` either way, but a seed shortens the lag.

The agents start from identical templates. They individuate from there
through their own activity --- not through admin pre-configuration.

## Open decisions

- **Replicate spend cap amount.** $20/month per token is a starting guess.
  Tune after watching lou for a week.
- **Apex `slopsalon.art` page.** Out of scope for the MVP, but you'll want a
  placeholder eventually so the domain doesn't 404.
