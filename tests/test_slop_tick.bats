#!/usr/bin/env bats

setup() {
    TEST_HOME="$(mktemp -d)"
    AGENT_NAME="testagent"
    AGENT_DIR="$TEST_HOME/slop-salon-$AGENT_NAME"
    mkdir -p "$AGENT_DIR"
    cd "$AGENT_DIR"
    git init -q -b main
    git config user.email "t@example.com"
    git config user.name "Test"
    git config commit.gpgsign false
    echo "initial" > seed.txt
    git add seed.txt
    git commit -q -m "seed"

    STUB_DIR="$(mktemp -d)"
    cat > "$STUB_DIR/claude" <<'EOF'
#!/usr/bin/env bash
# Stub: record the prompt claude was invoked with, then write a tick artifact so
# a commit happens. Read the LAST argument, not $2: slop-tick also passes flags
# (--print, --disallowedTools ...) ahead of the prompt, and a positional $2
# silently captured a flag name the moment one was added.
printf '%s' "${!#}" > "$HOME/claude-prompt.txt"
echo "tick-output" > "$PWD/tick-$$.txt"
EOF
    chmod +x "$STUB_DIR/claude"

    # Default slop-studio stub: emits nothing, so the prompt is unchanged.
    # Individual tests override it to exercise the cue-prepend path.
    cat > "$STUB_DIR/slop-studio" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
    chmod +x "$STUB_DIR/slop-studio"

    # Wrap git so `push` is a no-op (no remote in test)
    REAL_GIT="$(command -v git)"
    cat > "$STUB_DIR/git" <<EOF
#!/usr/bin/env bash
if [[ "\$1" == "push" || "\$1" == "pull" ]]; then
    exit 0
fi
exec "$REAL_GIT" "\$@"
EOF
    chmod +x "$STUB_DIR/git"

    # Stub pgrep so slop-tick's tailscaled-ensure check no-ops in the test.
    cat > "$STUB_DIR/pgrep" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
    chmod +x "$STUB_DIR/pgrep"

    # Stub pkill so the orphan-shell reap is a hermetic no-op. The real
    # `pkill -f "shell-snapshots/snapshot-zsh"` would match (and kill) the
    # host's own shells when the suite runs inside an agent harness.
    cat > "$STUB_DIR/pkill" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
    chmod +x "$STUB_DIR/pkill"

    # Codex runner stubs. `codex` records its full argv the same way the claude
    # stub does; `slop-prompt` records that it was asked to render AGENTS.md.
    cat > "$STUB_DIR/codex" <<'EOF'
#!/usr/bin/env bash
printf '%s' "$*" > "$HOME/codex-argv.txt"
echo "tick-output" > "$PWD/tick-$$.txt"
EOF
    chmod +x "$STUB_DIR/codex"

    cat > "$STUB_DIR/slop-prompt" <<'EOF'
#!/usr/bin/env bash
printf '%s' "$*" > "$HOME/slop-prompt-argv.txt"
EOF
    chmod +x "$STUB_DIR/slop-prompt"

    export PATH="$STUB_DIR:$PATH"
    export HOME="$TEST_HOME"
    export AGENT_NAME

    SCRIPT="$BATS_TEST_DIRNAME/../templates/slop-tick"
}

teardown() {
    rm -rf "$TEST_HOME" "$STUB_DIR"
}

@test "fails without AGENT_NAME" {
    unset AGENT_NAME
    run bash "$SCRIPT" "tick"
    [ "$status" -ne 0 ]
    [[ "$output" == *"AGENT_NAME"* ]]
}

@test "fails without prompt argument" {
    run bash "$SCRIPT"
    [ "$status" -ne 0 ]
    [[ "$output" == *"usage"* ]]
}

@test "denies AskUserQuestion, which no --print tick can answer" {
    # rahel's 08:00 tick spent a whole API call composing a question and got
    # `is_error: true` back --- there is no human in a tick to answer it.
    cat > "$STUB_DIR/claude" <<'EOF'
#!/usr/bin/env bash
printf '%s' "$*" > "$HOME/claude-argv.txt"
echo "tick-output" > "$PWD/tick-$$.txt"
EOF
    chmod +x "$STUB_DIR/claude"

    run bash "$SCRIPT" "tick"
    [ "$status" -eq 0 ]
    grep -q -- "--disallowedTools AskUserQuestion" "$HOME/claude-argv.txt"
}

@test "SLOP_DENIED_TOOLS overrides the denied-tool list" {
    cat > "$STUB_DIR/claude" <<'EOF'
#!/usr/bin/env bash
printf '%s' "$*" > "$HOME/claude-argv.txt"
echo "tick-output" > "$PWD/tick-$$.txt"
EOF
    chmod +x "$STUB_DIR/claude"

    SLOP_DENIED_TOOLS="AskUserQuestion WebSearch" run bash "$SCRIPT" "tick"
    [ "$status" -eq 0 ]
    grep -q -- "--disallowedTools AskUserQuestion WebSearch" "$HOME/claude-argv.txt"
}

@test "runs claude and creates a commit when files change" {
    run bash "$SCRIPT" "tick"
    [ "$status" -eq 0 ]
    cd "$AGENT_DIR"
    log_count=$(git log --oneline | wc -l)
    [ "$log_count" -ge 2 ]
}

@test "disables git auto-gc/maintenance so a detached gc can't pin the lock" {
    run bash "$SCRIPT" "tick"
    [ "$status" -eq 0 ]
    cd "$AGENT_DIR"
    # A backgrounded `git gc --auto --detach` would inherit the flock fd and
    # keep it open after the tick exits, stalling every later wake as `busy`.
    [ "$(git config --get gc.auto)" = "0" ]
    [ "$(git config --get maintenance.auto)" = "false" ]
}

@test "skips cleanly when another tick holds the sprite lock" {
    cd "$AGENT_DIR"
    initial_count=$(git log --oneline | wc -l)

    # Hold the lock the way an in-flight tick would (fd 8 keeps the flock).
    exec 8>"$TEST_HOME/.slop-tick.lock"
    flock -n 8

    run bash "$SCRIPT" "tick"

    exec 8>&-

    [ "$status" -eq 75 ]
    [[ "$output" == *"already running"* ]]

    # No tick ran: no new commit.
    cd "$AGENT_DIR"
    [ "$(git log --oneline | wc -l)" -eq "$initial_count" ]
}

@test "commits pre-tick leftovers before pulling" {
    # A crashed tick (or a sprite fs rollback to a mid-tick checkpoint) leaves
    # uncommitted files that would block `git pull` with "untracked working
    # tree files would be overwritten by merge". Re-wrap git so the pull stub
    # snapshots the log, proving the leftovers commit lands *before* the pull.
    cat > "$STUB_DIR/git" <<EOF
#!/usr/bin/env bash
if [[ "\$1" == "pull" ]]; then
    "$REAL_GIT" log --format=%s > "\$HOME/log-at-pull.txt"
    exit 0
fi
if [[ "\$1" == "push" ]]; then
    exit 0
fi
exec "$REAL_GIT" "\$@"
EOF
    chmod +x "$STUB_DIR/git"

    cd "$AGENT_DIR"
    echo "orphaned by a crashed tick" > leftover.txt

    run bash "$SCRIPT" "tick"
    [ "$status" -eq 0 ]

    grep -q "pre-tick leftovers" "$TEST_HOME/log-at-pull.txt"

    # The leftover file is committed, and the tick's own work still lands as
    # its own commit afterwards.
    cd "$AGENT_DIR"
    [ -z "$("$REAL_GIT" ls-files --others --exclude-standard)" ]
    "$REAL_GIT" log --format=%s -1 | grep -qv "pre-tick leftovers"
}

@test "skips commit when nothing changed" {
    cat > "$STUB_DIR/claude" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
    chmod +x "$STUB_DIR/claude"

    cd "$AGENT_DIR"
    initial_count=$(git log --oneline | wc -l)

    run bash "$SCRIPT" "tick"
    [ "$status" -eq 0 ]

    cd "$AGENT_DIR"
    new_count=$(git log --oneline | wc -l)
    [ "$initial_count" -eq "$new_count" ]
}

@test "prepends the studio-state cue to a tick prompt" {
    cat > "$STUB_DIR/slop-studio" <<'EOF'
#!/usr/bin/env bash
echo "Studio state --- mirror line"
EOF
    chmod +x "$STUB_DIR/slop-studio"

    run bash "$SCRIPT" "tick"
    [ "$status" -eq 0 ]
    prompt="$(cat "$TEST_HOME/claude-prompt.txt")"
    [[ "$prompt" == *"Studio state --- mirror line"* ]]
    # The original "tick" prompt is preserved after the cue.
    [[ "$prompt" == *$'\n\ntick' ]]
}

@test "leaves the tick prompt unchanged when the cue is empty" {
    run bash "$SCRIPT" "tick"
    [ "$status" -eq 0 ]
    [ "$(cat "$TEST_HOME/claude-prompt.txt")" = "tick" ]
}

@test "does not prepend the cue to a non-tick (talk) prompt" {
    cat > "$STUB_DIR/slop-studio" <<'EOF'
#!/usr/bin/env bash
echo "Studio state --- should not appear"
EOF
    chmod +x "$STUB_DIR/slop-studio"

    run bash "$SCRIPT" "a one-shot prompt from the admin"
    [ "$status" -eq 0 ]
    [ "$(cat "$TEST_HOME/claude-prompt.txt")" = "a one-shot prompt from the admin" ]
}

@test "tick survives a failing slop-studio" {
    cat > "$STUB_DIR/slop-studio" <<'EOF'
#!/usr/bin/env bash
echo "boom" >&2
exit 1
EOF
    chmod +x "$STUB_DIR/slop-studio"

    run bash "$SCRIPT" "tick"
    [ "$status" -eq 0 ]
    [ "$(cat "$TEST_HOME/claude-prompt.txt")" = "tick" ]
}

# --- runner dispatch ------------------------------------------------------
#
# Which agent CLI drives the tick is a per-agent provider choice, carried in
# ~/.slop-provider as SLOP_RUNNER. The default must stay `claude`, because a
# sprite provisioned before the provider split has no such file.

@test "defaults to the claude runner when SLOP_RUNNER is unset" {
    run bash "$SCRIPT" "tick"
    [ "$status" -eq 0 ]
    [ -f "$HOME/claude-prompt.txt" ]
    [ ! -f "$HOME/codex-argv.txt" ]
}

@test "sources ~/.slop-provider, and it wins over a stale ~/.slop-env" {
    # The whole point of the split: swapping provider rewrites one small file,
    # and what it says overrides whatever inference config the older, bigger
    # file still exports.
    cat > "$HOME/.slop-env" <<EOF
export AGENT_NAME=$AGENT_NAME
export ANTHROPIC_MODEL=stale-qwen
EOF
    cat > "$HOME/.slop-provider" <<'EOF'
unset ANTHROPIC_BASE_URL ANTHROPIC_AUTH_TOKEN ANTHROPIC_API_KEY ANTHROPIC_MODEL
export SLOP_RUNNER=claude
export ANTHROPIC_MODEL=deepseek-v4-flash
EOF
    cat > "$STUB_DIR/claude" <<'EOF'
#!/usr/bin/env bash
printf '%s' "$ANTHROPIC_MODEL" > "$HOME/claude-model.txt"
echo "tick-output" > "$PWD/tick-$$.txt"
EOF
    chmod +x "$STUB_DIR/claude"

    run bash "$SCRIPT" "tick"
    [ "$status" -eq 0 ]
    [ "$(cat "$HOME/claude-model.txt")" = "deepseek-v4-flash" ]
}

@test "a subscription provider leaves no inference key set" {
    # claude resolves ANTHROPIC_API_KEY -> ANTHROPIC_AUTH_TOKEN -> the OAuth
    # profile, so subscription auth works only if the unset actually clears what
    # a pre-split ~/.slop-env exports.
    cat > "$HOME/.slop-env" <<EOF
export AGENT_NAME=$AGENT_NAME
export ANTHROPIC_AUTH_TOKEN=stale-vllm-token
export ANTHROPIC_BASE_URL=http://tailnet:8001
EOF
    cat > "$HOME/.slop-provider" <<'EOF'
unset ANTHROPIC_BASE_URL ANTHROPIC_AUTH_TOKEN ANTHROPIC_API_KEY ANTHROPIC_MODEL ANTHROPIC_SMALL_FAST_MODEL API_TIMEOUT_MS
export SLOP_RUNNER=claude
EOF
    cat > "$STUB_DIR/claude" <<'EOF'
#!/usr/bin/env bash
printf '%s|%s' "${ANTHROPIC_AUTH_TOKEN:-unset}" "${ANTHROPIC_BASE_URL:-unset}" > "$HOME/claude-auth.txt"
echo "tick-output" > "$PWD/tick-$$.txt"
EOF
    chmod +x "$STUB_DIR/claude"

    run bash "$SCRIPT" "tick"
    [ "$status" -eq 0 ]
    [ "$(cat "$HOME/claude-auth.txt")" = "unset|unset" ]
}

@test "SLOP_RUNNER=codex runs codex exec, not claude" {
    cat > "$HOME/.slop-provider" <<'EOF'
export SLOP_RUNNER=codex
EOF
    run bash "$SCRIPT" "tick"
    [ "$status" -eq 0 ]
    [ -f "$HOME/codex-argv.txt" ]
    [ ! -f "$HOME/claude-prompt.txt" ]
    grep -q -- "exec" "$HOME/codex-argv.txt"
    # The sprite is itself the sandbox (the agent has sudo and renders media),
    # so codex's own sandbox only gets in the way.
    grep -q -- "--sandbox danger-full-access" "$HOME/codex-argv.txt"
    # --ephemeral would skip the session files `slop usage` tallies.
    ! grep -q -- "--ephemeral" "$HOME/codex-argv.txt"
    # The prompt still reaches it.
    grep -q -- "tick" "$HOME/codex-argv.txt"
}

@test "codex ticks render AGENTS.md first; claude ticks do not" {
    # Codex has no `@` import syntax, so CLAUDE.md's SOUL/MEMORY/TOOLS imports
    # would silently vanish from the prompt --- the same quiet failure as the
    # oversize SIBLINGS.md that broke a tick step on all six agents for weeks.
    cat > "$HOME/.slop-provider" <<'EOF'
export SLOP_RUNNER=codex
EOF
    run bash "$SCRIPT" "tick"
    [ "$status" -eq 0 ]
    grep -q -- "agents-md" "$HOME/slop-prompt-argv.txt"

    rm -f "$HOME/slop-prompt-argv.txt" "$HOME/.slop-provider"
    run bash "$SCRIPT" "tick"
    [ "$status" -eq 0 ]
    [ ! -f "$HOME/slop-prompt-argv.txt" ]
}

@test "an unknown runner fails loudly rather than guessing" {
    cat > "$HOME/.slop-provider" <<'EOF'
export SLOP_RUNNER=gemini
EOF
    run bash "$SCRIPT" "tick"
    [ "$status" -ne 0 ]
    [[ "$output" == *"unknown SLOP_RUNNER"* ]]
}

@test "a missing slop-prompt does not block a codex tick" {
    # Fail-open: a stale AGENTS.md beats no tick at all.
    rm -f "$STUB_DIR/slop-prompt"
    cat > "$HOME/.slop-provider" <<'EOF'
export SLOP_RUNNER=codex
EOF
    run bash "$SCRIPT" "tick"
    [ "$status" -eq 0 ]
    [ -f "$HOME/codex-argv.txt" ]
}
