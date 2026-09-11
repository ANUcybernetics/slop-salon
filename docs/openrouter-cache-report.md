# DeepSeek prompt caching caps at ~3328 tokens via OpenRouter

Report prepared for OpenRouter. Post it in the `#help` forum on
<https://discord.gg/openrouter> --- that is where OpenRouter takes bug reports;
`support@openrouter.ai` is billing and account only, and there is no public
issue tracker for the routing API. Their SDK repos (`OpenRouterTeam/*`) are the
wrong venue.

Reply to expect: Discord is community-first and slow. If it goes unanswered, the
same evidence is worth sending to DeepSeek, since we have not established which
side of the boundary the fault sits on (see "What we could not determine").

## Summary

Every DeepSeek model we have tried through OpenRouter's Anthropic-compatible
endpoint caches at most ~3328 prompt tokens per request, regardless of how large
the prompt grows. Non-DeepSeek models on the same endpoint, same account, same
key and same client cache the full prefix. The effect is a 10--30x cost
difference on an agent workload.

## Setup

- Client: Claude Code 2.1.263, unmodified,
  `ANTHROPIC_BASE_URL=https://openrouter.ai/api`
- Auth: one `OPENROUTER_API_KEY`, one account, for every model below
- Models pinned to first-party hosts via OpenRouter presets
- Workload: a long-running agent loop --- one session makes 40--100 calls, the
  prompt grows from ~27k to ~150k tokens, append-only (no compaction)

## Observed, in production

Cache hit rate is `cache_read / (input + cache_read)`, summed per session.

| model                                   | hit rate |
| --------------------------------------- | -------- |
| `deepseek/deepseek-v4.1-flash`          | 7--8%    |
| `deepseek/deepseek-v4-flash-vision-exp` | 21--30%  |
| `z-ai/glm-5.3-flash`                    | 83--96%  |
| `meta/muse-spark-1.3-contributor`       | 77--90%  |

Nine agents, three per model, identical harness. The split is by model, with no
overlap.

## The A/B that isolates it

One agent, one machine, one prompt, run twice. The only change between runs was
the model string; the Claude Code build, system prompt, tool set and
conversation were identical.

`deepseek/deepseek-v4.1-flash` --- 7.5% overall:

```
call 0  prompt=27137  input=27137  cache_read=0        0%
call 1  prompt=28708  input=25380  cache_read=3328    12%
call 2  prompt=36340  input=32756  cache_read=3584    10%
```

`z-ai/glm-5.3-flash` --- 31.9% overall, still warming:

```
call 0  prompt=26421  input=26421  cache_read=0        0%
call 1  prompt=27982  input=27278  cache_read=704      3%
call 2  prompt=35381  input=7413   cache_read=27968   79%
```

Call 2 is the comparison. GLM read back 27968 tokens --- essentially all of call
1's 27982-token prompt. DeepSeek read back 3584 of a 36340-token prompt and
stopped.

3328 and 3584 are 52 and 56 blocks of 64. The same ceiling appears in unrelated
production sessions hours apart, so it reads as a cap rather than a prefix
mismatch: if the prefix were diverging we would expect the cut point to move
with the content.

## What we ruled out

Each of these was probed directly against both models, side by side, through the
same endpoint and key. All cached at 84--95% on **both** --- that is, none of
them reproduces the fault:

| probe                                        | deepseek-v4.1 | glm-5.3 |
| -------------------------------------------- | ------------- | ------- |
| identical prompt, repeated                   | 99%           | 99%     |
| growing conversation, ~15k                   | 89%           | 89%     |
| + 14 tool definitions                        | 91%           | 91%     |
| + extended thinking fed back verbatim        | 89%           | 89%     |
| production scale, ~100k prompt               | 95%           | 95%     |
| multiple rolling `cache_control` breakpoints | 93%           | 93%     |
| a real agent transcript, replayed            | 68%           | 68%     |

Also ruled out: client version (all sprites on 2.1.263), client settings and
hooks, host routing (both models pinned first-party), prompt scale, images (they
appear far later in the conversation than the point where caching stops), and
conversation content --- the replay row above is the affected agent's own
transcript, and it scores the same on both models.

## What we could not determine

We have no minimal reproduction. Every synthetic request we built caches
correctly on DeepSeek; the cap only appears against Claude Code's real request,
whose system-plus-tools block we cannot fully reconstruct from outside. So the
trigger is something in that block interacting with the DeepSeek route, and we
cannot say whether the fault is in OpenRouter's Anthropic translation layer or
in DeepSeek's upstream caching.

To reproduce: point Claude Code 2.1.263 at `https://openrouter.ai/api` with
`ANTHROPIC_BASE_URL`, run any multi-step task that grows the context past ~30k,
and compare `cache_read_input_tokens` across calls for a DeepSeek model against
any non-DeepSeek model.

## What would help

- whether the ~3328-token ceiling is a known limit on DeepSeek routes
- whether it is OpenRouter's translation or DeepSeek's upstream
- whether a different request shape avoids it

Generation IDs are available on request; note that `/api/v1/generation?id=`
returns 404 for IDs more than a few hours old, so we can supply fresh ones if
you want to inspect specific calls.
