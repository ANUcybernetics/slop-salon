# cybersonic-vllm

Local vLLM service for `Qwen/Qwen3.6-35B-A3B-FP8` --- a sparse-MoE
agentic-coding and tool-calling model from the Qwen3.6 family, served
FP8-quantised --- on cybersonic's 6x RTX 3090 (24 GB each). Tensor parallel TP=4
across GPUs 0-3, exposed as model id `qwen3.6-27b` (a stable label kept across
model swaps) at `http://cybersonic:8001/v1` under the OpenAI-compatible API.
Managed by a user-level systemd unit.

GPUs 4 and 5 sit outside the TP group but are not ours to assume: the box is
shared, and another user's vLLM has occupied GPU 4 (2026-07-28). Treat "spare
card" plans --- moving TP off a suspect GPU, hosting a draft model --- as
needing a check first.

At the defaults this lands at 8.8 GiB of weights per card and 8.4 GiB of KV
cache, which vLLM reports as 861,477 tokens --- 6.57x concurrency at the full
131,072-token context, so the six agents each get a full-context slot without
queueing.

This directory lives in the [slop-salon](../) admin repo --- it is the vLLM
deployment for the Slop Salon collective --- but runs only on the `cybersonic`
GPU box.

## Quickstart

On cybersonic, from a `slop-salon` checkout, in this `cybersonic-vllm/`
directory:

```bash
mise trust                           # trust this subdir's Python 3.12 pin
uv sync                              # vllm-nightly + flashinfer + cuda-13 torch
cp .env.example .env                 # then set VLLM_API_KEY in it
chmod 600 .env
ln -sf "$PWD/systemd/cybersonic-vllm.service" \
  ~/.config/systemd/user/cybersonic-vllm.service
systemctl --user daemon-reload
loginctl enable-linger               # so the service survives logout
systemctl --user enable --now cybersonic-vllm.service
```

`VLLM_API_KEY` is the bearer key vLLM enforces; it must match the sprites'
`ANTHROPIC_AUTH_TOKEN`. The systemd unit's `WorkingDirectory` and `ExecStart`
paths are absolute --- adjust them to wherever this directory sits on
cybersonic.

First boot downloads ~37.5 GB of FP8 weights into `$HF_HOME`
(`/data/$USER/cache/huggingface` on cybersonic). Watch readiness with
`tail -f logs/service.log` --- the API starts accepting requests once the
workers finish loading.

## Use

curl:

```bash
curl -sS http://cybersonic:8001/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen3.6-27b",
    "messages": [{"role": "user", "content": "Summarise the difference between async and threading in three lines."}]
  }' | jq .choices[0].message
```

Python (OpenAI SDK), with a tool definition and the Qwen think block:

```python
from openai import OpenAI

client = OpenAI(base_url="http://cybersonic:8001/v1", api_key="not-needed")

resp = client.chat.completions.create(
    model="qwen3.6-27b",
    messages=[{"role": "user", "content": "What's the weather in Canberra?"}],
    tools=[{
        "type": "function",
        "function": {
            "name": "get_weather",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    }],
)

msg = resp.choices[0].message
print("answer:", msg.content)
print("tool_calls:", msg.tool_calls)
print("thinking:", (msg.model_extra or {}).get("reasoning"))   # vLLM 0.21+ extension field
```

To suppress the think block for a single request, pass
`extra_body={"chat_template_kwargs": {"enable_thinking": False}}` to the call.

## Operations

- status: `systemctl --user status cybersonic-vllm`
- restart: `systemctl --user restart cybersonic-vllm`
- logs: `tail -f logs/service.log`
- **speculative decoding is off** (2026-07-28). vLLM wedged a TP worker roughly
  every 20-30 min under the collective's load --- EngineCore dying on a
  shm-broadcast `TimeoutError` waiting for a worker that had stopped answering,
  three times in ninety minutes, each time killing every in-flight tick. The
  crash never names a kernel, so the logs cannot single out which of the three
  experimental features in play is responsible (MTP spec decode, the Mamba-mode
  prefix cache, this dev-nightly build). MTP went first: newest and most
  intricate path, spec tokens scheduled at every crash, and much the cheapest to
  lose (~1.5-2x generation speed, against a prefix cache the multi-turn agent
  loop depends on). Re-enable with
  `SPEC_DECODE='{"method":"qwen3_next_mtp","num_speculative_tokens":2}'`. If
  crashes persist without it, the cause is elsewhere --- move to the prefix
  cache next, and only then the build.
- tuning: env-overridable knobs (MODEL, PORT, GPUS, TP, MAX_MODEL_LEN,
  GPU_MEM_UTIL, ...) are documented at the top of `scripts/launch_vllm.sh`. For
  permanent changes edit the `Environment=` lines in
  `systemd/cybersonic-vllm.service`, then
  `systemctl --user daemon-reload && systemctl --user restart cybersonic-vllm`.

## Health prober

`Restart=always` on the service is not enough, and cannot be made enough.
`ExecStart` is `uv run vllm serve`, and `uv run` waits on its child rather than
exec'ing it, so systemd supervises `uv` --- not vLLM. On 2026-07-28 a TP worker
hung, EngineCore died on a shm-broadcast `TimeoutError`, and the API server's
clean shutdown then blocked on that wedged worker. `uv` sat waiting forever, the
unit stayed `active (running)`, the restart never fired, and :8001 refused every
connection for four hours while `systemctl` was green on both boxes. **systemd
cannot detect a hung process**, so this needs a prober outside the service:

- `cybersonic-vllm-health.timer` --- fires `scripts/health_check.sh` every 60s
  (relative to the last probe finishing, so a slow probe can't stack up).
- it restarts the unit after `FAILURES_BEFORE_RESTART` (3) consecutive bad
  probes, i.e. ~3 minutes of continuous failure.
- a bad probe is **only** an unanswered port or `/health` returning 503 (what
  vLLM returns on `EngineDeadError`). Any other status --- 401 from an API-key
  change, 404 from a route rename --- counts as alive on purpose: restarting a
  working server once a minute is a far worse failure than missing a stall.
- `WARMUP_SEC` (900) suppresses probing for 15 min after activation. A cold
  start serves nothing for ~160s, so probing inside that window would
  restart-loop the service and never let it finish booting.
- state and log: `~/.local/state/cybersonic-vllm/health-failures`,
  `logs/health.log` (user-unit journals aren't readable on this box without the
  `adm` group, so the script tees to a file).

Install (or re-install after edits):

```sh
cp systemd/cybersonic-vllm-health.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now cybersonic-vllm-health.timer
```

Knobs are env overrides, so a one-off can be checked by hand without touching
the unit --- `WARMUP_SEC=0 scripts/health_check.sh` probes immediately. When
changing it, verify the restart branch against a throwaway unit
(`UNIT=some-test.service PORT=9999 FAILURES_BEFORE_RESTART=1`) rather than by
bouncing vLLM.
