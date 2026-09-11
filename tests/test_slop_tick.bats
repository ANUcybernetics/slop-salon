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
    # Stub claude: record argv, then write a tick artifact so a commit happens.
    cat > "$STUB_DIR/claude" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" > "$HOME/claude-argv.txt"
echo "tick-output" > "$PWD/tick-$$.txt"
EOF
    chmod +x "$STUB_DIR/claude"

    # Wrap git so push/pull are no-ops (no remote in test).
    REAL_GIT="$(command -v git)"
    cat > "$STUB_DIR/git" <<EOF
#!/usr/bin/env bash
if [[ "\$1" == "push" || "\$1" == "pull" ]]; then
    echo "git \$1" >> "\$HOME/git-calls.txt"
    exit 0
fi
exec "$REAL_GIT" "\$@"
EOF
    chmod +x "$STUB_DIR/git"

    # pkill would otherwise match (and kill) the host's own shells.
    printf '#!/usr/bin/env bash\nexit 0\n' > "$STUB_DIR/pkill"
    chmod +x "$STUB_DIR/pkill"

    export HOME="$TEST_HOME"
    export AGENT_NAME
    export PATH="$STUB_DIR:$PATH"
    SLOP_TICK="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)/templates/slop-tick"
}

teardown() {
    rm -rf "$TEST_HOME" "$STUB_DIR"
}

@test "fails without AGENT_NAME" {
    unset AGENT_NAME
    run "$SLOP_TICK" "tick"
    [ "$status" -ne 0 ]
    [[ "$output" == *"AGENT_NAME"* ]]
}

@test "fails without a prompt" {
    run "$SLOP_TICK"
    [ "$status" -ne 0 ]
    [[ "$output" == *"usage"* ]]
}

@test "runs claude -p with the prompt, the env's model and the denied tools, then commits and pushes" {
    export ANTHROPIC_MODEL="z-ai/glm-5.3-flash@preset/x"
    run "$SLOP_TICK" "tick"
    [ "$status" -eq 0 ]
    argv="$(cat "$HOME/claude-argv.txt")"
    [[ "$argv" == *"-p"* ]]
    [[ "$argv" == *"tick"* ]]
    [[ "$argv" == *"--model"* ]]
    [[ "$argv" == *"z-ai/glm-5.3-flash@preset/x"* ]]
    [[ "$argv" == *"--disallowedTools"* ]]
    [[ "$argv" == *"AskUserQuestion"* ]]
    git log --oneline | grep -q "session"
    grep -q "git pull" "$HOME/git-calls.txt"
    grep -q "git push" "$HOME/git-calls.txt"
}

@test "passes no --model when ANTHROPIC_MODEL is unset" {
    unset ANTHROPIC_MODEL
    run "$SLOP_TICK" "tick"
    [ "$status" -eq 0 ]
    ! grep -q -- "--model" "$HOME/claude-argv.txt"
}

@test "SLOP_DENIED_TOOLS overrides the denied-tool list" {
    export SLOP_DENIED_TOOLS="AskUserQuestion,WebSearch"
    run "$SLOP_TICK" "tick"
    [ "$status" -eq 0 ]
    grep -q "AskUserQuestion,WebSearch" "$HOME/claude-argv.txt"
}

@test "commits pre-tick leftovers before pulling" {
    echo "orphan" > "$AGENT_DIR/notes-leftover.txt"
    run "$SLOP_TICK" "tick"
    [ "$status" -eq 0 ]
    git log --format=%s | grep -q "pre-tick leftovers"
    [ "$(git log --oneline | wc -l)" -eq 3 ]
}

@test "skips the commit when nothing changed" {
    cat > "$STUB_DIR/claude" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
    run "$SLOP_TICK" "tick"
    [ "$status" -eq 0 ]
    [ "$(git log --oneline | wc -l)" -eq 1 ]
    ! grep -q "git push" "$HOME/git-calls.txt" 2>/dev/null
}

@test "a failed claude still commits partial work and says so on stderr" {
    cat > "$STUB_DIR/claude" <<'EOF'
#!/usr/bin/env bash
echo "partial" > "$PWD/partial.txt"
exit 1
EOF
    run "$SLOP_TICK" "tick"
    [ "$status" -eq 0 ]
    [[ "$output" == *"slop-tick: claude exited 1"* ]]
    git log --oneline | grep -q "session"
}

@test "reads nothing from disk but the repo: no env file is sourced" {
    printf 'export AGENT_NAME=someone-else\n' > "$HOME/.slop-env"
    run "$SLOP_TICK" "tick"
    [ "$status" -eq 0 ]
    [ -f "$AGENT_DIR/tick-"*.txt ]
}
