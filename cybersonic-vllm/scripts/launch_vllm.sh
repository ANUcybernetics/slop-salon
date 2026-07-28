#!/usr/bin/env bash
# Serve Qwen/Qwen3.6-35B-A3B-FP8 (sparse-MoE, FP8, agentic / tool-calling)
# on cybersonic's 5x RTX 3090 (TP=4 over GPUs 0-3; GPU 4 idle).
#
# Why these defaults:
#   - 35B-A3B is a sparse MoE: ~35B total params but only ~3B active per
#     token, so compute per token --- prefill and decode --- is far below
#     a dense 27B. The FP8 checkpoint is ~37.5 GB (~9.4 GB/GPU over TP=4);
#     BF16 (~67 GB) left no room for the KV cache on these 24 GB cards.
#   - FP8 on these Ampere 3090s runs weight-only (W8A16) via the Marlin
#     dequant kernel --- there are no native FP8 tensor cores, but the
#     ~2x weight-memory saving is the point and Marlin still speeds up
#     the memory-bound decode. vLLM prints a "no native FP8" notice.
#   - Qwen3-Next-family hybrid: interleaved Gated DeltaNet (linear attn)
#     and full attention keeps per-token KV cost low, so a 128K context
#     fits on 3090s.
#   - self-speculative decoding via the model's own MTP head
#     (method=qwen3_next_mtp) is a lossless ~1.5-2x on generation with no
#     draft model and no extra GPU, but it is OFF by default as of
#     2026-07-28 --- see SPEC_DECODE below. (Draft-model speculation is
#     broken by the DeltaNet recurrent state, so the MTP head is the only
#     coherent option if it is re-enabled.)
#   - --reasoning-parser qwen3 + --enable-auto-tool-choice
#     + --tool-call-parser qwen3_coder are mandatory for the OpenAI-style
#     API to surface thinking blocks and tool calls as structured fields.
#   - --limit-mm-per-prompt pins image/video to 0; the model is multimodal
#     but this deployment is text/tool-call only, freeing the MM cache.
#   - --enable-prefix-caching is explicit because vLLM's default (None)
#     resolves to OFF for this hybrid DeltaNet model; the agent workload
#     is a multi-turn loop that re-sends a growing shared prefix each turn,
#     so caching it cuts prefill cost dramatically. (Opts into vLLM's
#     experimental Mamba-mode prefix cache for the DeltaNet layers.)
#
# Override via env (any of):
#   MODEL=Qwen/Qwen3.6-27B          # dense 27B --- the rollback model
#   PORT=8001
#   HOST=0.0.0.0                    # 127.0.0.1 to restrict to localhost
#   GPUS=0,1,2,3                    # comma-separated CUDA indices
#   TP=4                            # tensor-parallel degree; must equal len(GPUS)
#   MAX_MODEL_LEN=131072            # bump up to 262144 for native 256K
#   MAX_NUM_BATCHED_TOKENS=8192
#   GPU_MEM_UTIL=0.90
#   SERVED_NAME=qwen3.6-27b         # OpenAI-API `model` field; kept as the
#                                   # 27b label so a model swap needs no
#                                   # change to agents' ANTHROPIC_MODEL
#   SPEC_DECODE='{"method":"qwen3_next_mtp","num_speculative_tokens":2}'
#                                   # empty (the default) disables speculative
#                                   # decoding entirely --- see below
#
# Driver requirement: NVIDIA 580+ (CUDA 13). flashinfer-jit-cache +
# flashinfer-cubin ship precompiled kernels so no system CUDA toolkit is
# needed --- if anything still tries to JIT, install cuda-toolkit-13-0
# and `export CUDA_HOME=/usr/local/cuda` before launch.

set -euo pipefail

MODEL="${MODEL:-Qwen/Qwen3.6-35B-A3B-FP8}"
PORT="${PORT:-8001}"
HOST="${HOST:-0.0.0.0}"
GPUS="${GPUS:-0,1,2,3}"
TP="${TP:-4}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-131072}"
MAX_NUM_BATCHED_TOKENS="${MAX_NUM_BATCHED_TOKENS:-8192}"
GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.90}"
SERVED_NAME="${SERVED_NAME:-qwen3.6-27b}"

# Speculative decoding, off unless SPEC_DECODE carries a --speculative-config
# JSON blob. Disabled 2026-07-28 after vLLM wedged a TP worker roughly every
# 20-30 min under the collective's load: EngineCore died on a shm-broadcast
# TimeoutError waiting for a worker that had stopped answering, three times in
# ninety minutes, each time taking every in-flight agent tick with it.
#
# Not proven to be the cause --- the crash is always a worker going silent, never
# a Python-level error naming a kernel, so the logs can't single out one of the
# three experimental features in play (MTP spec decode, the Mamba-mode prefix
# cache, this dev-nightly build). MTP is first on the list because it is the
# newest and most intricate path, spec tokens were scheduled at every crash, and
# it is the cheapest of the three to give up: ~1.5-2x slower generation, versus
# losing the prefix cache that keeps the agent loop's growing shared prefix
# affordable. If crashes continue with this off, the cause is elsewhere and the
# only thing spent was speed.
SPEC_DECODE="${SPEC_DECODE:-}"

IFS=',' read -ra GPU_LIST <<< "$GPUS"
if (( ${#GPU_LIST[@]} != TP )); then
  echo "error: this launcher expects TP=${TP} to equal len(GPUS)=${#GPU_LIST[@]} (GPUS=${GPUS})" >&2
  echo "       (single-instance only; multi-worker DP isn't wired up here)" >&2
  exit 1
fi

cd "$(dirname "$0")/.."
mkdir -p logs

export CUDA_VISIBLE_DEVICES="$GPUS"

args=(
  --host "$HOST"
  --port "$PORT"
  --served-model-name "$SERVED_NAME"
  --tensor-parallel-size "$TP"
  --max-model-len "$MAX_MODEL_LEN"
  --max-num-batched-tokens "$MAX_NUM_BATCHED_TOKENS"
  --gpu-memory-utilization "$GPU_MEM_UTIL"
  --enable-prefix-caching
  --limit-mm-per-prompt '{"image":8,"video":0}'
  --reasoning-parser qwen3
  --enable-auto-tool-choice
  --tool-call-parser qwen3_coder
)

if [[ -n $SPEC_DECODE ]]; then
  args+=(--speculative-config "$SPEC_DECODE")
  echo "launch_vllm: speculative decoding ENABLED: $SPEC_DECODE" >&2
else
  echo "launch_vllm: speculative decoding disabled (set SPEC_DECODE to re-enable)" >&2
fi

exec uv run vllm serve "$MODEL" "${args[@]}"
