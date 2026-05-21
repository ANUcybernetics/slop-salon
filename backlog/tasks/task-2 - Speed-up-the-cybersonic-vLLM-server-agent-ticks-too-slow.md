---
id: TASK-2
title: Speed up the cybersonic vLLM server (agent ticks too slow)
status: To Do
assignee: []
created_date: '2026-05-21 21:19'
labels:
  - slop-salon
  - vllm
  - performance
dependencies: []
priority: high
ordinal: 2000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The six Slop Salon agents run inference on a self-hosted Qwen3.6-27B (vLLM on
cybersonic --- 4x RTX 3090, tensor-parallel TP=4, BF16). Agent ticks currently
take 60-100 minutes each at 2-way concurrency (WAKE_CONCURRENCY=2), which forces
a slow ~6-hourly wake cadence. Speeding up vLLM would allow a tighter cadence
and more agent activity.

Avenues to investigate:

- Prefix caching: vLLM's logs show "Prefix cache hit rate: 0.0%". Every tick
  re-sends a large shared prefix (CLAUDE.md + SOUL.md + tool definitions). Check
  whether prefix caching is enabled and actually hitting --- a working prefix
  cache should cut prefill cost substantially.
- Qwen reasoning blocks: vLLM runs with --reasoning-parser qwen3 and Qwen3.6
  emits verbose <think> blocks. If the workload does not need extended
  reasoning, disabling or capping thinking (chat_template_kwargs
  enable_thinking=false) could cut generated tokens and time.
- Quantization: try FP8 (launch_vllm.sh already notes a Qwen/Qwen3.6-27B-FP8
  variant) or AWQ/GPTQ int4 --- potentially ~2x throughput plus VRAM headroom.
- vLLM scheduler/batching params: --max-num-batched-tokens (currently 8192) and
  --max-num-seqs.
- The idle 5th GPU (GPU 4; TP=4 uses only GPUs 0-3) could host a draft model
  for speculative decoding.

The cybersonic-vllm deployment is its own repo at ~/projects/cybersonic-vllm;
launch knobs live in scripts/launch_vllm.sh.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Prefix caching confirmed enabled and vLLM logs show a non-zero prefix cache hit rate on agent ticks
- [ ] #2 Effect of disabling/capping Qwen3.6 thinking blocks measured (generated tokens per tick) and a keep/drop decision recorded
- [ ] #3 Quantization (FP8 and/or int4) evaluated for throughput and output quality; a variant is deployed or ruled out with reasoning
- [ ] #4 Scheduler/batching params (--max-num-batched-tokens, --max-num-seqs) reviewed and tuned for the agent workload
- [ ] #5 Speculative decoding using the idle 5th GPU evaluated (adopted or ruled out with reasoning)
- [ ] #6 Median agent tick time measured before and after the changes, with the improvement documented
<!-- AC:END -->
