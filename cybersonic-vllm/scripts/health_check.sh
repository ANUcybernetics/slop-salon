#!/usr/bin/env bash
# Restart vLLM when it has stopped serving but still looks alive to systemd.
#
# The outage this exists for (2026-07-28, ~4h dark): a TP worker hung; EngineCore
# hit a shm-broadcast TimeoutError and died; the API server's clean shutdown then
# blocked on that wedged worker. `ExecStart` is `uv run vllm serve`, and `uv run`
# waits on its child rather than exec'ing it, so systemd was supervising a `uv`
# that sat waiting forever. The unit stayed `active (running)`, `Restart=always`
# never fired, and :8001 refused every connection --- green on both boxes while
# the whole collective was down.
#
# systemd cannot detect a hung process, so no amount of unit-file work fixes
# this: it needs a prober outside the service. That is this script.
#
# It acts on exactly the two signatures of that outage:
#   - the port does not answer (connection refused, or no reply within TIMEOUT)
#   - /health returns 503, which is what vLLM returns on EngineDeadError
#     (vllm/entrypoints/serve/instrumentator/health.py)
#
# ANY other HTTP status counts as alive, deliberately. A 401 from an API-key
# middleware change or a 404 from a route rename means the server is answering
# requests; restarting a working server every minute is a far worse failure than
# missing a stall, so the prober stays narrow and only ever acts on "not
# answering" and "engine dead".

set -euo pipefail

PORT="${PORT:-8001}"
UNIT="${UNIT:-cybersonic-vllm.service}"
TIMEOUT="${TIMEOUT:-10}"
# Consecutive bad probes before restarting. At the timer's 60s cadence this is
# ~3 minutes of continuous failure --- long enough that a brief stall under load
# rides out, short enough that a real stall costs minutes rather than hours.
FAILURES_BEFORE_RESTART="${FAILURES_BEFORE_RESTART:-3}"
# Grace after the unit becomes active. A cold start (weight load + CUDA graph
# capture + compile) serves nothing for ~160s, so probing inside this window
# would restart-loop the service forever and never let it finish booting.
WARMUP_SEC="${WARMUP_SEC:-900}"

STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/cybersonic-vllm"
COUNTER="$STATE_DIR/health-failures"
LOG_DIR="$(cd "$(dirname "$0")/.." && pwd)/logs"
LOG="$LOG_DIR/health.log"

mkdir -p "$STATE_DIR" "$LOG_DIR"

# Without curl every probe would read as "unreachable" and this script would
# restart a perfectly healthy vLLM once a minute forever. Bail loudly instead.
if ! command -v curl >/dev/null; then
	printf '[%s] curl not on PATH --- cannot probe; doing nothing\n' "$(date -Is)" >&2
	exit 1
fi

say() {
	# Both streams: the journal (via the unit) and a file, since user-unit
	# journals on this box are not readable without the adm group.
	printf '[%s] %s\n' "$(date -Is)" "$*" | tee -a "$LOG"
}

# Serialise probes so a slow restart can't race the next firing into a second
# restart of a service that is already coming back up.
exec 9>"$STATE_DIR/health.lock"
if ! flock -n 9; then
	exit 0
fi

read_counter() {
	local n
	n="$(cat "$COUNTER" 2>/dev/null || echo 0)"
	[[ $n =~ ^[0-9]+$ ]] || n=0
	printf '%s' "$n"
}

# Only probe a unit systemd itself considers up. While activating, failed, or
# stopped, `Restart=always` is the mechanism in charge and a restart from here
# would just fight it.
state="$(systemctl --user show "$UNIT" --property=ActiveState --value 2>/dev/null || echo unknown)"
if [[ $state != active ]]; then
	say "unit $UNIT is $state, not active --- leaving it to systemd"
	printf '0' >"$COUNTER"
	exit 0
fi

# Age of the current activation, from the monotonic clock so it is immune to
# wall-clock steps (NTP, suspend).
active_us="$(systemctl --user show "$UNIT" --property=ActiveEnterTimestampMonotonic --value 2>/dev/null || echo 0)"
[[ $active_us =~ ^[0-9]+$ ]] || active_us=0
now_us="$(awk '{printf "%d", $1 * 1000000}' /proc/uptime)"
if ((active_us > 0 && now_us > active_us)); then
	active_age=$(((now_us - active_us) / 1000000))
else
	active_age=0
fi

if ((active_age < WARMUP_SEC)); then
	# Reset rather than merely skip: a fresh activation makes any failures
	# counted against the previous one irrelevant.
	printf '0' >"$COUNTER"
	exit 0
fi

# `curl -w '%{http_code}'` prints 000 itself when it cannot connect, so there is
# nothing to substitute in on failure --- an `|| echo 000` fallback here appends a
# *second* 000, and the resulting "000\n000" matches neither guard below, which
# silently classifies an unreachable server as healthy. `|| true` on the
# assignment (not inside it) is what keeps `set -e` from aborting on curl's
# non-zero exit.
code="$(curl -s -o /dev/null -w '%{http_code}' --max-time "$TIMEOUT" \
	"http://127.0.0.1:${PORT}/health" 2>/dev/null)" || true
[[ $code =~ ^[0-9]{3}$ ]] || code=000

if [[ $code != 000 && $code != 503 ]]; then
	prev="$(read_counter)"
	if ((prev > 0)); then
		say "healthy again (HTTP $code) after $prev bad probe(s)"
	fi
	printf '0' >"$COUNTER"
	exit 0
fi

reason="unreachable"
[[ $code == 503 ]] && reason="/health 503 (engine dead)"

n=$(($(read_counter) + 1))
printf '%s' "$n" >"$COUNTER"
say "bad probe $n/$FAILURES_BEFORE_RESTART: $reason (active ${active_age}s)"

if ((n < FAILURES_BEFORE_RESTART)); then
	exit 0
fi

say "restarting $UNIT after $n consecutive bad probes: $reason"
printf '0' >"$COUNTER"
# KillMode=mixed + TimeoutStopSec on the unit is what makes this reliable: the
# hung main process is SIGTERMed, then the whole cgroup (TP workers holding GPU
# memory included) is SIGKILLed at the timeout, so the restart cannot race the
# old process for :8001 or for VRAM.
if systemctl --user restart "$UNIT"; then
	say "restart issued"
else
	say "restart FAILED (exit $?)"
	exit 1
fi
