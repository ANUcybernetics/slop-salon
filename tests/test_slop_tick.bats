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
# Stub: record the prompt claude was invoked with (claude --print "<prompt>",
# so $2), then write a tick artifact so a commit happens.
printf '%s' "$2" > "$HOME/claude-prompt.txt"
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

@test "runs claude and creates a commit when files change" {
    run bash "$SCRIPT" "tick"
    [ "$status" -eq 0 ]
    cd "$AGENT_DIR"
    log_count=$(git log --oneline | wc -l)
    [ "$log_count" -ge 2 ]
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
