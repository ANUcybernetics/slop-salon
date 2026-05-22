# cybersonic-vllm

Local vLLM service for `Qwen/Qwen3.6-35B-A3B-FP8` --- a sparse-MoE
agentic-coding and tool-calling model from the Qwen3.6 family, served
FP8-quantised --- on cybersonic's 5x RTX 3090. Tensor parallel TP=4
across GPUs 0-3 (GPU 4 idle), exposed as model id `qwen3.6-27b` (a stable
label kept across model swaps) at `http://cybersonic:8001/v1` under the
OpenAI-compatible API. Managed by a user-level systemd unit.

This directory lives in the [slop-salon](../) admin repo --- it is the
vLLM deployment for the Slop Salon collective --- but runs only on the
`cybersonic` GPU box.

## Quickstart

On cybersonic, from a `slop-salon` checkout, in this `cybersonic-vllm/`
directory:

```bash
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
`ANTHROPIC_AUTH_TOKEN`. The systemd unit's `WorkingDirectory` and
`ExecStart` paths are absolute --- adjust them to wherever this directory
sits on cybersonic.

First boot downloads ~37.5 GB of FP8 weights into `$HF_HOME`
(`/data/$USER/cache/huggingface` on cybersonic). Watch readiness with
`tail -f logs/service.log` --- the API starts accepting requests once
the workers finish loading.

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
`extra_body={"chat_template_kwargs": {"enable_thinking": False}}` to
the call.

## Operations

- status: `systemctl --user status cybersonic-vllm`
- restart: `systemctl --user restart cybersonic-vllm`
- logs: `tail -f logs/service.log`
- tuning: env-overridable knobs (MODEL, PORT, GPUS, TP, MAX_MODEL_LEN,
  GPU_MEM_UTIL, ...) are documented at the top of
  `scripts/launch_vllm.sh`. For permanent changes edit the
  `Environment=` lines in `systemd/cybersonic-vllm.service`, then
  `systemctl --user daemon-reload && systemctl --user restart cybersonic-vllm`.
